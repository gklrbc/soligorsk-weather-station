#pragma once

// === Отправка данных ===
// Раз в 5 минут — как старая станция: сравнимость с историей февраля (§8.3),
// 288 записей/сутки, watchdog бота «молчание > 15 мин» = 3 пропущенных цикла.
#define SEND_INTERVAL_S   300
// Серия замеров внутри окна: медиана давит шум, не меняя частоту отправки
#define SAMPLES_PER_SEND  5
#define SAMPLE_GAP_S      5      // пауза между замерами серии
#define MIN_GOOD_SAMPLES  3      // меньше — серия не удалась
#define FW_VERSION        "2.0"
#define STATUS_PORT       80     // LAN-страница статуса и журнала станции

// === I2C (NodeMCU): D1 = SCL, D2 = SDA, адрес BME280 ищется 0x77/0x76 ===
#define I2C_SDA           4      // GPIO4 = D2
#define I2C_SCL           5      // GPIO5 = D1
#define I2C_CLOCK_HZ      50000  // 10–50 кГц по §11 (длинный кабель)

// === Индикация и связь ===
#define LED_PIN           2      // D4, встроенный LED, активный LOW
#define HTTP_TIMEOUT_MS   8000
#define WIFI_WAIT_MS      20000  // сколько ждать reconnect в цикле отправки
#define WIFI_REBOOT_MS    600000UL // дольше без сети — ESP.restart()
#define BOT_FAIL_ALERT    3      // неудач /update подряд до алерта
#define RSSI_ALERT_DBM    -80    // порог качества Wi-Fi (телеметрия связи)
#define ALERT_FLOOD_MS    3600000UL // антифлуд алертов одного типа: раз в час
