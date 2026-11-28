/*
 * Метеостанция «Солигорск» — прошивка NodeMCU (ESP8266), v2.1 (2026-11-24)
 *
 * Цикл: серия замеров BME280 (forced mode) → медиана → очередь на флеше
 * → батч-отправка /update_batch на бот (до 200 замеров за раз).
 * Ошибки датчика/бота/слабый RSSI — алерты через GET /alert (антифлуд раз в час).
 * Секреты и адрес бота — в include/secrets.h (шаблон: secrets.h.example).
 * Распиновка и правила ESP8266 — AGENTS.md §4.
 *
 * v2: OTA-обновление по воздуху (пароль OTA_PASS), LAN-страница статуса
 *     на порту 80 (показания + журнал событий), телеметрия (RSSI/ОЗУ/
 *     аптайм/прошивка) в каждом /update.
 * v2.1: store-and-forward — замеры буферизуются на флеше, пока бот
 *     недоступен, и доехали пакетом после возврата (честные ts через NTP);
 *     персистентный журнал событий на флеше (переживает рестарт);
 *     телеметрия дополнена причиной/счётчиком рестартов и размером очереди.
 *
 * Стенд-тест без малины: BOT_HOST = IP ПК, BOT_PORT = 5002 (стендовый TestV3).
 */
#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <ESP8266WebServer.h>
#include <ArduinoOTA.h>
#include <LittleFS.h>
#include <Wire.h>
#include <time.h>
#include <Adafruit_BME280.h>

#include "config.h"
#include "secrets.h"

static Adafruit_BME280 bme;
static bool sensorOk = false;
static uint8_t sensorAddr = 0;
static uint8_t botFailStreak = 0;
static unsigned long lastSend = 0;
static unsigned long wifiDownSince = 0;
static unsigned long lastAlertMs[3] = {0, 0, 0};  // заполняется в setup() «в прошлом»
static bool timeSynced = false;                    // NTP: честное время для ts замеров

// === Кольцевой журнал событий (RAM, 64 записи) + персистентная копия на флеше ===
#define LOG_RING_SIZE 64
#define EVT_PATH       "/events.log"
#define EVT_MAX_BYTES  8192
struct LogEntry {
  unsigned long ts;   // мс с момента старта
  char text[44];
};
static LogEntry s_log[LOG_RING_SIZE];
static uint8_t s_logHead = 0, s_logCount = 0;

// === Очередь замеров store-and-forward (файл /buf.csv на флеше) ===
#define BUF_PATH      "/buf.csv"
#define BUF_MAX_ROWS  1000

// === Статус-страница на LAN (порт STATUS_PORT, только локальная сеть) ===
ESP8266WebServer statusServer(STATUS_PORT);

void logEvent(const char *text) {
  LogEntry &e = s_log[s_logHead];
  e.ts = millis();
  strncpy(e.text, text, sizeof(e.text) - 1);
  e.text[sizeof(e.text) - 1] = '\0';
  s_logHead = (s_logHead + 1) % LOG_RING_SIZE;
  if (s_logCount < LOG_RING_SIZE) s_logCount++;
  Serial.println(String("[LOG] ") + text);

  // Персистентная копия: переживает рестарт (файл до 8 КБ, потом режется пополам)
  File f = LittleFS.open(EVT_PATH, "a");
  if (!f) return;
  f.println(String(millis() / 1000) + "s " + text);
  f.close();
  File chk = LittleFS.open(EVT_PATH, "r");
  if (!chk) return;
  size_t sz = chk.size();
  if (sz > EVT_MAX_BYTES) {
    String all = chk.readString();
    chk.close();
    int cut = all.indexOf('\n', all.length() / 2);
    if (cut > 0) {
      LittleFS.remove(EVT_PATH);
      File w = LittleFS.open(EVT_PATH, "w");
      if (w) { w.print(all.substring(cut + 1)); w.close(); }
    }
  } else {
    chk.close();
  }
}

// === Вспомогательное ===

// Типы алертов (антифлуд по каждому типу отдельно)
enum AlertType : uint8_t {
    ALERT_SENSOR_FAIL = 0,
    ALERT_BOT_FAIL,
    ALERT_RSSI_LOW,
    ALERT_COUNT
};

// Медиана из n значений (n = 5): сортировка вставками, отбрасывание выбросов
static float medianOf(float *a, uint8_t n) {
    for (uint8_t i = 1; i < n; i++) {
        float key = a[i];
        int8_t j = i - 1;
        while (j >= 0 && a[j] > key) { a[j + 1] = a[j]; j--; }
        a[j + 1] = key;
    }
    return a[n / 2];
}

// percent-encoding: /alert и /update получают текст только в URL
static void urlEncode(const char *src, char *dst, size_t dstSize) {
    static const char *hex = "0123456789ABCDEF";
    size_t di = 0;
    for (const unsigned char *p = (const unsigned char *)src;
         *p && di + 4 < dstSize; p++) {
        unsigned char c = *p;
        if ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
            (c >= '0' && c <= '9') || c == '-' || c == '_' || c == '.' || c == '~') {
            dst[di++] = (char)c;
        } else {
            dst[di++] = '%';
            dst[di++] = hex[c >> 4];
            dst[di++] = hex[c & 0x0F];
        }
    }
    dst[di] = '\0';
}

// GET к боту. Возвращает HTTP-код (200 = ОК) или <0 при сетевой ошибке.
static int httpGet(const char *url) {
    WiFiClient client;
    HTTPClient http;
    if (!http.begin(client, BOT_HOST, BOT_PORT, url)) return -1;
    http.setTimeout(HTTP_TIMEOUT_MS);
    http.setReuse(false);
    int code = http.GET();
    http.end();
    return code;
}

static bool sendAlert(AlertType type, const char *text) {
    unsigned long now = millis();
    if (now - lastAlertMs[type] < ALERT_FLOOD_MS) return false;  // антифлуд раз в час
    char enc[256];
    urlEncode(text, enc, sizeof(enc));
    char url[320];
    snprintf(url, sizeof(url), "/alert?key=%s&text=%s", STATION_KEY, enc);
    int code = httpGet(url);
    if (code == 200) {
        lastAlertMs[type] = now;
        Serial.printf("[ALERT] отправлен: %s\n", text);
    } else {
        Serial.printf("[ALERT] не доставлен (код %d): %s\n", code, text);
    }
    return code == 200;
}

// === Wi-Fi ===

static bool ensureWiFi() {
    if (WiFi.status() == WL_CONNECTED) {
        if (wifiDownSince != 0) {
            logEvent("wifi: связь восстановлена");
            Serial.println("[NET] Wi-Fi восстановлен");
        }
        wifiDownSince = 0;
        return true;
    }
    unsigned long start = millis();
    if (wifiDownSince == 0) {
        wifiDownSince = start;
        logEvent("wifi: связь потеряна");
        Serial.println("[NET] Wi-Fi потерян, пробую reconnect");
    }
    WiFi.reconnect();
    while (WiFi.status() != WL_CONNECTED && millis() - start < WIFI_WAIT_MS) {
        delay(100);
        ESP.wdtFeed();
    }
    if (WiFi.status() == WL_CONNECTED) {
        Serial.printf("[NET] Wi-Fi подключён, RSSI %ld dBm\n", (long)WiFi.RSSI());
        wifiDownSince = 0;
        return true;
    }
    Serial.println("[NET] Wi-Fi недоступен");
    if (millis() - wifiDownSince > WIFI_REBOOT_MS) {
        logEvent("wifi: нет связи — перезагрузка");
        Serial.println("[NET] долго без сети — перезагрузка");
        ESP.restart();
    }
    return false;
}

// === NTP: честное время для ts замеров ===

static String utcNowString() {
    time_t now = time(nullptr);
    struct tm tmv;
    gmtime_r(&now, &tmv);
    char buf[24];
    strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", &tmv);
    return String(buf);
}

static void ensureTimeSync() {
    if (timeSynced) return;
    // UTC: честные timestamps замеров, бот хранит UTC и показывает в местном
    configTime(0, 0, "pool.ntp.org", "time.nist.gov");
    unsigned long start = millis();
    while (time(nullptr) < 1600000000 && millis() - start < 10000UL) {
        delay(200);
        ESP.wdtFeed();
    }
    timeSynced = time(nullptr) > 1600000000;
    if (timeSynced) {
        logEvent("время синхронизировано (NTP)");
        Serial.println("[NTP] время синхронизировано");
    } else {
        Serial.println("[NTP] не синхронизировалось — попробуем в следующем цикле");
    }
}

// === BME280 ===

static bool initSensor() {
    static const uint8_t addrs[2] = {0x77, 0x76};
    for (uint8_t i = 0; i < 2; i++) {
        if (bme.begin(addrs[i], &Wire)) {
            sensorAddr = addrs[i];
            // Forced mode: одно измерение по команде — минимум самонагрева
            bme.setSampling(Adafruit_BME280::MODE_FORCED,
                            Adafruit_BME280::SAMPLING_X1,
                            Adafruit_BME280::SAMPLING_X1,
                            Adafruit_BME280::SAMPLING_X1,
                            Adafruit_BME280::FILTER_OFF,
                            Adafruit_BME280::STANDBY_MS_1000);
            sensorOk = true;
            char buf[40];
            snprintf(buf, sizeof(buf), "датчик найден: 0x%02X", sensorAddr);
            logEvent(buf);
            Serial.printf("[BME] найден на 0x%02X\n", sensorAddr);
            return true;
        }
    }
    sensorOk = false;
    logEvent("датчик: не найден на шине I2C");
    Serial.println("[BME] не найден (0x77/0x76)");
    return false;
}

// === LED ===
// Норма — вспышка раз в ~8 с; нет Wi-Fi — две вспышки; нет датчика — три.
static void ledUpdate() {
    const unsigned long slotMs = 100;  // вспышка 100 мс, темнота 100 мс
    uint8_t pulses = 1;
    unsigned long pauseSlots = 79;     // цикл ~8.2 с
    if (!sensorOk) {
        pulses = 3;
        pauseSlots = 17;               // цикл ~2.3 с
    } else if (WiFi.status() != WL_CONNECTED) {
        pulses = 2;
        pauseSlots = 18;
    }
    unsigned long total = (unsigned long)pulses * 2 + pauseSlots;
    unsigned long t = (millis() / slotMs) % total;
    bool on = (t % 2 == 0) && (t / 2 < pulses);
    digitalWrite(LED_PIN, on ? LOW : HIGH);
}

// === Очередь замеров (store-and-forward) ===
// Каждый замер пишется в /buf.csv строкой "ts,t,h,p".
// flushQueue() отправляет до 200 строк батчем на /update_batch и удаляет
// отправленное. Если бот недоступен — строки копятся, ротация по лимиту.

static size_t queueCount() {
    File f = LittleFS.open(BUF_PATH, "r");
    if (!f) return 0;
    size_t n = 0;
    while (f.available()) {
        if (f.readStringUntil('\n').length()) n++;
    }
    f.close();
    return n;
}

static void trimQueueTo(size_t target) {
    File f = LittleFS.open(BUF_PATH, "r");
    if (!f) return;
    String keep;
    size_t n = 0;
    while (f.available()) {
        String line = f.readStringUntil('\n');
        if (line.length()) n++;
        if (n > target) { keep += line; keep += '\n'; }
    }
    f.close();
    LittleFS.remove(BUF_PATH);
    File w = LittleFS.open(BUF_PATH, "w");
    if (w) { w.print(keep); w.close(); }
}

static void queueReading(float t, float h, float p, const String &ts) {
    File f = LittleFS.open(BUF_PATH, "a");
    if (!f) { Serial.println("[BUF] не открыть файл очереди"); return; }
    f.println(String(ts) + "," + String(t, 2) + "," + String(h, 2) + "," + String(p, 2));
    f.close();
}

static bool flushQueue() {
    size_t n = queueCount();
    if (n == 0) return true;
    if (n > BUF_MAX_ROWS) trimQueueTo(BUF_MAX_ROWS / 2);

    File f = LittleFS.open(BUF_PATH, "r");
    if (!f) return false;
    String json = "{\"readings\":[";
    bool first = true;
    size_t taken = 0;
    String keep;
    while (f.available()) {
        String line = f.readStringUntil('\n');
        line.trim();
        if (!line.length()) continue;
        if (taken < 200) {
            json += (first ? "" : ",") + line;
            first = false;
            taken++;
        } else {
            keep += line;
            keep += '\n';
        }
    }
    f.close();

    WiFiClient client;
    HTTPClient http;
    String uri = String("/update_batch?key=") + STATION_KEY;
    if (!http.begin(client, BOT_HOST, BOT_PORT, uri)) return false;
    http.addHeader("Content-Type", "application/json");
    http.setTimeout(HTTP_TIMEOUT_MS * 4);
    int code = http.POST(json);
    http.end();
    if (code != 200) {
        Serial.printf("[BUF] батч не принят (код %d), строки остаются в очереди\n", code);
        return false;
    }
    // Отправленные строки удалить: перезаписать файл остатком
    LittleFS.remove(BUF_PATH);
    if (keep.length()) {
        File w = LittleFS.open(BUF_PATH, "w");
        if (w) { w.print(keep); w.close(); }
    }
    char buf[48];
    snprintf(buf, sizeof(buf), "очередь: отправлено %u замеров", (unsigned)taken);
    logEvent(buf);
    return true;
}

// === Цикл измерения и отправки ===

static void doCycle() {
    bool wifiOk = ensureWiFi();
    if (wifiOk) ensureTimeSync();   // NTP: честные ts для очереди
    ESP.wdtFeed();

    if (!sensorOk && !initSensor()) {
        sendAlert(ALERT_SENSOR_FAIL, "Датчик BME280 не отвечает");
        return;
    }

    // Серия замеров: forced-режим + паузы, медиана давит выбросы
    float ts[SAMPLES_PER_SEND], hs[SAMPLES_PER_SEND], ps[SAMPLES_PER_SEND];
    uint8_t good = 0;
    for (uint8_t i = 0; i < SAMPLES_PER_SEND && good < SAMPLES_PER_SEND; i++) {
        if (i > 0) delay(SAMPLE_GAP_S * 1000UL);
        ESP.wdtFeed();
        if (!bme.takeForcedMeasurement()) continue;
        float t = bme.readTemperature();
        float h = bme.readHumidity();
        float p = bme.readPressure() * 760.0f / 101325.0f;  // Па → мм рт. ст.
        if (isnan(t) || isnan(h) || isnan(p)) continue;
        ts[good] = t;
        hs[good] = h;
        ps[good] = p;
        good++;
    }
    if (good < MIN_GOOD_SAMPLES) {
        if (sensorOk) logEvent("датчик: серия не удалась");
        sensorOk = false;
        sendAlert(ALERT_SENSOR_FAIL, "Датчик BME280 не отвечает");
        return;
    }
    if (!sensorOk) {
        logEvent("датчик: восстановлен");
        sensorOk = true;
    }
    float t = medianOf(ts, good);
    float h = medianOf(hs, good);
    float p = medianOf(ps, good);

    // 1) Замер в очередь с честным ts. Без NTP замер в очередь не пишется:
    //    бот проставит время приёма через обычный /update.
    if (timeSynced) {
        queueReading(t, h, p, utcNowString());
    } else {
        Serial.println("[BUF] время не синхронизировано — замер только онлайн-путём");
    }

    // 2) Сеть есть — доехать очередь батчем (включая только что записанный замер)
    bool flushed = false;
    if (wifiOk) flushed = flushQueue();

    // 3) Если батч не доехал, а очередь пуста — запасной путь: обычный /update
    if (!flushed && queueCount() == 0 && wifiOk) {
        char url[192];
        snprintf(url, sizeof(url),
                 "/update?key=%s&t=%.2f&h=%.2f&p=%.2f"
                 "&rssi=%d&heap=%u&up=%lu&fw=" FW_VERSION,
                 STATION_KEY, t, h, p,
                 (int)WiFi.RSSI(), (unsigned)ESP.getFreeHeap(),
                 (unsigned long)(millis() / 1000));
        int code = httpGet(url);
        if (code == 200) {
            botFailStreak = 0;
            Serial.printf("[TX] t=%.2f h=%.2f p=%.2f — OK\n", t, h, p);
        } else {
            botFailStreak++;
            Serial.printf("[TX] отказ, код %d (серия %u)\n", code, botFailStreak);
            if (botFailStreak >= BOT_FAIL_ALERT) {
                char msg[96];
                snprintf(msg, sizeof(msg),
                         "Нет связи с ботом: %d неудач /update подряд", botFailStreak);
                sendAlert(ALERT_BOT_FAIL, msg);
            }
        }
    }

    long rssi = WiFi.RSSI();
    if (rssi < RSSI_ALERT_DBM) {
        char msg[80];
        snprintf(msg, sizeof(msg), "Слабый Wi-Fi сигнал: %ld dBm", (long)rssi);
        sendAlert(ALERT_RSSI_LOW, msg);
    }
}

// === Стандартные функции ===

void setup() {
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, HIGH);  // выключен (активный LOW)
    Serial.begin(115200);
    delay(100);
    Serial.println("\n=== Метеостанция «Солигорск», NodeMCU v2.1 ===");

    // ФС: персистентный журнал + очередь замеров
    if (!LittleFS.begin()) {
        LittleFS.format();
        LittleFS.begin();
    }

    // первый алерт каждого типа должен уходить сразу: «в прошлом» на час
    for (uint8_t i = 0; i < ALERT_COUNT; i++) lastAlertMs[i] = 0UL - ALERT_FLOOD_MS;

    WiFi.mode(WIFI_STA);
    WiFi.persistent(false);
    WiFi.setAutoReconnect(true);
    WiFi.hostname("meteo-soligorsk");
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    ensureWiFi();
    ensureTimeSync();

    Wire.begin(I2C_SDA, I2C_SCL);
    Wire.setClock(I2C_CLOCK_HZ);
    // BME280 в forced-режиме растягивает clock, дефолтных 230 мкс мало
    Wire.setClockStretchLimit(10000);

    // OTA: обновление прошивки по Wi-Fi, пароль из secrets.h
    ArduinoOTA.setHostname("meteo-soligorsk");
    ArduinoOTA.setPassword(OTA_PASS);
    ArduinoOTA.onStart([]() {
        logEvent("OTA: старт обновления");
        digitalWrite(LED_PIN, LOW);
    });
    ArduinoOTA.onEnd([]() {
        logEvent("OTA: обновление завершено");
        digitalWrite(LED_PIN, HIGH);
    });
    ArduinoOTA.onError([](ota_error_t err) {
        char buf[40];
        snprintf(buf, sizeof(buf), "OTA: ошибка (код %d)", (int)err);
        logEvent(buf);
    });
    ArduinoOTA.begin();

    // Статус-страница и журнал на LAN (порт STATUS_PORT)
    statusServer.on("/", []() {
        String s = "Метеостанция «Солигорск» · прошивка v" FW_VERSION "\n";
        s += "wifi rssi: " + String(WiFi.RSSI()) + " dBm\n";
        s += "heap: " + String(ESP.getFreeHeap()) + " B\n";
        s += "uptime: " + String(millis() / 1000) + " с\n";
        s += "датчик: " + String(sensorOk ? "OK" : "ОШИБКА") + "\n";
        s += "очередь замеров: " + String(queueCount()) + " шт\n";
        s += "\n— журнал событий (новые сверху) —\n";
        for (uint8_t k = 0; k < s_logCount; k++) {
            uint8_t i = (s_logHead + LOG_RING_SIZE - 1 - k) % LOG_RING_SIZE;
            s += String(s_log[i].ts / 1000) + "s: " + s_log[i].text + "\n";
        }
        statusServer.send(200, "text/plain; charset=utf-8", s);
    });
    statusServer.begin();

    initSensor();
    logEvent("старт станции");

    doCycle();          // первый замер сразу — перезапуск виден по свежей записи
    lastSend = millis();
}

void loop() {
    ESP.wdtFeed();
    ArduinoOTA.handle();
    statusServer.handleClient();
    ledUpdate();
    if (millis() - lastSend >= SEND_INTERVAL_S * 1000UL) {
        lastSend = millis();
        doCycle();
    }
    delay(10);
}
