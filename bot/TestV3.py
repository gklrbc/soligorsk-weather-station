# TestV3 — Telegram-бот метеостанции «Солигорск»
# Полная версия: всё из TestV2 + весь набор фич. Один файл, без .env — только блок КОНФИГУРАЦИЯ.
#
# Относительно TestV2 добавлено:
#   1. Точка росы (формула Магнуса): кнопка в меню + в «Погода сейчас».
#   2. Алерт «температура резко скакнула» — дельта > JUMP_LIMIT °C за 30 мин.
#   3. Морозный алерт: T ниже FROST_THRESHOLD → предупреждение (коулдаун 6ч).
#   4. Человекочитаемый uptime: «3 сут 12 ч», плюс время старта бота.
#   5. График 24ч: температура + влажность второй линией на второй оси.
#   6. График точки росы за неделю.
#   7. Кнопка «💾 Бэкап сейчас»: мгновенный бэкап + .db файлом прямо в чат.
#   8. Экспорт Excel (настоящий .xlsx собирается zipfile'ом, без openpyxl).
#   9. Эндпоинт /alert — труба для будущих RPM-алертов из прошивки ESP32:
#      станция шлёт GET /alert?key=<SENSOR_KEY>&text=<сообщение>, бот рассылает всем.
#  10. Счётчик отказов /update за 24ч в «Статус системы».
#  11. Дайджест честно пишет «данных не было», если пусто.
#  12. «Погода сейчас» показывает возраст замера: «замер N мин назад».
#  13. Тренд давления за 3 часа (стрелка вверх/вниз/ровно).
#  14. Восход/закат для Солигорска (NOAA-приближение) в сводке.
#  15. /stats — сводка 24ч / 7д / 30д с min/max/avg.
#
# Новое в TestV2 (унаследовано): ключ и валидация /update, watchdog «станция молчит»,
# алерт «ошибка датчика», дайджест 21:00, ночные бэкапы с ротацией, лог-файл,
# рекорды 24ч по T/H/P, график за 30 дней, /id, /promo.

import asyncio
import aiosqlite
import sqlite3
import datetime
import io
import math
import time
import os
import sys
import signal
import random
import psutil
import logging
import logging.handlers
import zipfile
from typing import Optional, List, Tuple
from threading import Thread, Lock
from collections import deque
from flask import Flask, request, redirect, Response, render_template, send_file

# Без монитора — Agg-бэкенд matplotlib
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# pyplot держит глобальное состояние и не потокобезопасен: Flask обрабатывает
# запросы картинок параллельно, поэтому рендер сериализуется этим замком.
_PLT_LOCK = Lock()

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, BufferedInputFile, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramAPIError

# --- КОНФИГУРАЦИЯ ---
TOKEN = "REDACTED_OLD_BOT_TOKEN"

# TODO(пользователь): перегенерировать токен в BotFather — старый засвечен в коде/репо

# Секретный ключ /update и /alert: станция шлёт /update?key=<SENSOR_KEY>&t=..&h=..&p=..
# TODO(пользователь): вписать ключ в прошивку ESP32 после развёртывания TestV3
SENSOR_KEY = "REDACTED_OLD_STATION_KEY"

ADMIN_PASS = "REDACTED_OLD_ADMIN_PASS"

# ВАЖНО: Проверь путь к диску (df -h). Если диск в /media/pi/..., поменяй путь ниже.
DISK_PATH = "/mnt/weather_data"
DB_NAME = os.path.join(DISK_PATH, "weather.db")
BACKUP_DIR = os.path.join(DISK_PATH, "backups")
LOG_DIR = "logs"

TIMEZONE_OFFSET = "+3 hours"      # Солигорск (UTC+3)
LOCAL_TZ_SHIFT = datetime.timedelta(hours=3)
# Солигорск: округлённый центр города (точные координаты — в secrets_local.py)
CITY_LAT = 52.04
CITY_LON = 27.54

DIGEST_HOUR = 21                  # час суток (мест.), в который уходит дайджест
SILENCE_LIMIT_MIN = 15            # станция не писала N минут -> алерт «молчит»
CHECK_INTERVAL_S = 300            # период фоновых проверок (5 минут)
TREND_CHECK_INTERVAL_S = 600      # период проверки тренда T (10 минут)
JUMP_LIMIT_C = 5.0                # сколько °C за 30 мин = «резко»
JUMP_COOLDOWN_S = 3 * 3600        # анти-флуд скачка: 3 часа
FROST_THRESHOLD_C = -20.0         # порог морозного алерта
FROST_COOLDOWN_S = 6 * 3600       # анти-флуд мороза: 6 часов
ALERT_COOLDOWN_S = 3600           # анти-флуд по умолчанию: час
BACKUP_KEEP = 7                   # сколько бэкапов держать
BACKUP_INTERVAL_S = 24 * 3600     # раз в сутки
ESP_ALERT_MAX_LEN = 400           # лимит длины текста от ESP

# Sanity-диапазоны входящих данных станции (вне диапазона = ошибка датчика)
TEMP_RANGE = (-60.0, 55.0)        # °C
HUM_RANGE = (0.0, 100.0)          # %
PRES_RANGE = (300.0, 1100.0)      # мм рт. ст.

# Граница брака в БД: отказ датчика 2026-02-15 19:20:49 мест. (UTC в БД)
BAD_DATA_FROM = "2026-02-15 16:20:49"

TEST_MODE: bool = False

# --- ЛОГИРОВАНИЕ ---
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.TimedRotatingFileHandler(
            os.path.join(LOG_DIR, "bot.log"), when="midnight", backupCount=14, encoding="utf-8"
        ),
    ],
)
logging.getLogger('werkzeug').setLevel(logging.ERROR)
logger = logging.getLogger("testv3")

# --- ИНИЦИАЛИЗАЦИЯ ---
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Заблокированные через веб-админку пользователи: бот молча игнорирует
# их сообщения (включая /start и FSM-состояния) и не включает их в рассылки.
_blocked_uids_cache = None
_blocked_uids_ts = 0.0
BLOCKED_CACHE_TTL_S = 60


async def get_blocked_uids() -> set:
    """Множество заблокированных user_id; кэш на BLOCKED_CACHE_TTL_S."""
    global _blocked_uids_cache, _blocked_uids_ts
    now = time.time()
    if _blocked_uids_cache is None or now - _blocked_uids_ts > BLOCKED_CACHE_TTL_S:
        rows = await execute_query(
            "SELECT user_id FROM users WHERE IFNULL(blocked, 0) = 1", fetch=True)
        _blocked_uids_cache = {int(r[0]) for r in (rows or [])}
        _blocked_uids_ts = now
    return _blocked_uids_cache


def invalidate_blocked_cache() -> None:
    """Сброс кэша после блокировки/разблокировки через веб-админку
    (Flask живёт в том же процессе — эффект мгновенный)."""
    global _blocked_uids_cache, _blocked_uids_ts
    _blocked_uids_cache = None
    _blocked_uids_ts = 0.0


@dp.message.outer_middleware()
async def blocked_gate(handler, event: types.Message, data: dict):
    uid = getattr(event.from_user, "id", None)
    if uid and uid in await get_blocked_uids():
        logger.info("🚫 Сообщение от заблокированного %s — молча игнорируется", uid)
        return
    return await handler(event, data)

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__,
            template_folder=os.path.join(_BASE_DIR, 'web', 'templates'),
            static_folder=os.path.join(_BASE_DIR, 'web', 'static'))
BOT_START_TIME = time.time()
BOT_STARTED_AT_STR = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

reject_stamps: deque = deque(maxlen=500)   # метки отказов /update (Flask-поток пишет, loop читает)
_last_alert_at: dict = {}                  # таймштампы последних алертов по типам
silence_flag: bool = False                 # «станция молчит» сейчас активна?

# --- СЕССИИ ВЕБ-АДМИНКИ ---
WEB_SESSIONS: dict = {}                    # token -> время истечения
ADMIN_COOKIE = "ws_session"
WEB_SESSION_TTL_S = 12 * 3600
web_broadcast_queue: deque = deque(maxlen=20)  # тексты рассылок веб-админки


class DevStates(StatesGroup):
    waiting_for_manual_data = State()


# --- КЛАВИАТУРЫ ---
main_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="Погода сейчас"), KeyboardButton(text="Сводка за сегодня")],
    [KeyboardButton(text="Погода за период"), KeyboardButton(text="Пределы 24ч")],
    [KeyboardButton(text="💧 Точка росы"), KeyboardButton(text="📊 Статистика")],
], resize_keyboard=True)

period_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="За 24 часа"), KeyboardButton(text="За неделю")],
    [KeyboardButton(text="За месяц"), KeyboardButton(text="Точка росы (неделя)")],
    [KeyboardButton(text="Назад")]
], resize_keyboard=True)

limits_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="Макс °C"), KeyboardButton(text="Мин °C")],
    [KeyboardButton(text="Макс %"), KeyboardButton(text="Мин %")],
    [KeyboardButton(text="Макс давл"), KeyboardButton(text="Мин давл")],
    [KeyboardButton(text="Назад")]
], resize_keyboard=True)


def get_admin_kb() -> ReplyKeyboardMarkup:
    test_btn_text = "🧪 Тест без БД: ВКЛ" if TEST_MODE else "🧪 Тест без БД: ВЫКЛ"
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Статус системы"), KeyboardButton(text="📈 Аналитика")],
        [KeyboardButton(text="🌡 CPU и RAM"), KeyboardButton(text="🕒 Последние данные")],
        [KeyboardButton(text="📦 Экспорт CSV"), KeyboardButton(text="📊 Экспорт Excel")],
        [KeyboardButton(text="💾 Бэкап сейчас"), KeyboardButton(text="✍️ Внести данные")],
        [KeyboardButton(text="🧹 Очистить БД"), KeyboardButton(text="🛠 Тех. перерыв")],
        [KeyboardButton(text="✅ Возобновить"), KeyboardButton(text=test_btn_text)],
        [KeyboardButton(text="🪪 Мой ID"), KeyboardButton(text="ℹ️ Фичи")],
        [KeyboardButton(text="🚪 Выход")]
    ], resize_keyboard=True)


# --- ТЕСТОВЫЕ ДАННЫЕ (Режим разработчика) ---
def get_test_current_weather() -> Tuple[float, float, float]:
    return (round(random.uniform(-5, 25), 1), random.randint(40, 90), random.randint(730, 770))


def get_test_summary() -> str:
    periods = [("🌙", "Ночь"), ("🌅", "Утро"), ("☀️", "День"), ("🌆", "Вечер")]
    lines = ["📅 **Сводка за сегодня:**"]
    for icon, period in periods:
        lines.append(f"{icon} {period}: {round(random.uniform(0, 10), 1)}°C ... {round(random.uniform(10, 20), 1)}°C")
    return "\n".join(lines)


def get_test_chart_data(mode: str) -> List[Tuple]:
    """Синтетические ряды для проверки графиков без работающей станции.

    Сид фиксированный: при автообновлении картинка не должна «прыгать».
    Формат строк повторяет SQL-выборки: daily — (день, час, T, H, ts),
    weekly/monthly/dew — (метка, значение).
    """
    rnd = random.Random(20261118)
    now = datetime.datetime.now()

    if mode == 'daily':
        rows = []
        for i in range(24):
            ts = now - datetime.timedelta(hours=23 - i)
            hour = ts.hour
            # суточный ход: минимум ночью, максимум около 15:00
            temp = round(2.0 + 6.0 * math.sin(2 * math.pi * (hour - 9) / 24)
                         + rnd.uniform(-0.35, 0.35), 1)
            hum = max(40, min(96, round(84 - 1.8 * (temp - 2.0)
                                        + rnd.uniform(-2.5, 2.5))))
            rows.append((ts.strftime('%d'), f"{hour:02d}:00", temp, hum, i))
        return rows

    days = 7 if mode in ('weekly', 'dew') else 30
    rows = []
    for i in range(days):
        day = now - datetime.timedelta(days=days - 1 - i)
        label = day.strftime('%d.%m')
        # медленная волна погоды + шум «датчика»
        temp = round(1.5 + 4.5 * math.sin(2 * math.pi * i * 1.4 / max(days - 1, 1))
                     + rnd.uniform(-1.2, 1.2), 1)
        if mode == 'dew':
            hum = max(55, min(95, round(82 + 6 * math.sin(2 * math.pi * i / 5)
                                        + rnd.uniform(-3, 3))))
            rows.append((label, dew_point(temp, hum)))
        else:
            rows.append((label, temp))
    return rows


def get_test_limit(metric: str) -> Tuple[float, str]:
    sample = {
        'temp_max': random.uniform(10, 25), 'temp_min': random.uniform(-5, 10),
        'hum_max': random.uniform(70, 95), 'hum_min': random.uniform(30, 60),
        'pres_max': random.uniform(750, 770), 'pres_min': random.uniform(730, 750),
    }[metric]
    time_str = datetime.datetime.now().strftime('%H:%M')
    return (round(sample, 1), time_str)

# --- БАЗА ДАННЫХ ---
def init_db_sync() -> None:
    if not os.path.exists(DISK_PATH):
        try:
            os.makedirs(DISK_PATH)
        except Exception as e:
            logger.error(f"Не удалось создать директорию {DISK_PATH}: {e}")
            raise
    os.makedirs(BACKUP_DIR, exist_ok=True)

    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute('''CREATE TABLE IF NOT EXISTS weather_data
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                      temp REAL, hum REAL, pres REAL)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)''')
        conn.execute('''CREATE INDEX IF NOT EXISTS idx_weather_ts
                        ON weather_data(timestamp)''')

        # Миграции: добавляем недостающие колонки, если их ещё нет.
        def ensure_column(table: str, column: str, decl: str) -> None:
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
            if column not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

        # ВАЖНО: у TestV1 миграция last_active была сломана — ALTER с
        # DEFAULT CURRENT_TIMESTAMP запрещён в SQLite (неконстантный DEFAULT) и
        # тихо глотался except'ом. Из-за этого колонка так и не появлялась.
        ensure_column("users", "last_active", "DATETIME")
        ensure_column("users", "blocked", "INTEGER DEFAULT 0")
        # Разовая расстановка активности там, где её ещё нет
        conn.execute("UPDATE users SET last_active = CURRENT_TIMESTAMP "
                     "WHERE last_active IS NULL OR last_active = ''")

        conn.commit()


async def execute_query(query: str, params: Tuple = (), fetch: bool = False, fetch_one: bool = False):
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            if fetch:
                return await cursor.fetchall()
            if fetch_one:
                return await cursor.fetchone()
            await db.commit()
    except Exception as e:
        logger.error(f"🔥 Ошибка БД: {e}")
        return None
    return None


async def register_user(user_id: int) -> None:
    await execute_query("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    await execute_query(
        f"UPDATE users SET last_active = datetime('now', '{TIMEZONE_OFFSET}') WHERE user_id = ?",
        (user_id,)
    )

# --- АЛЕРТЫ И РАССЫЛКА ---
def alert_allowed(kind: str, cooldown: int = ALERT_COOLDOWN_S) -> bool:
    """Анти-флуд: каждый тип алерта не чаще своего коулдауна."""
    now = time.time()
    last = _last_alert_at.get(kind, 0)
    if now - last >= cooldown:
        _last_alert_at[kind] = now
        return True
    return False


async def broadcast(text: str) -> int:
    # Заблокированные админкой пользователи рассылок не получают
    users = await execute_query(
        "SELECT user_id FROM users WHERE IFNULL(blocked, 0) = 0", fetch=True)
    count = 0
    if users:
        for user in users:
            try:
                await bot.send_message(user[0], text)
                count += 1
                await asyncio.sleep(0.05)
            except TelegramAPIError:
                pass
    return count


async def send_alert(kind: str, text: str, cooldown: int = ALERT_COOLDOWN_S) -> None:
    if alert_allowed(kind, cooldown):
        await broadcast(text)

# --- МЕТЕО-МАТЕМАТИКА ---
def dew_point(t: float, h: float) -> Optional[float]:
    """Точка росы по Магнусу (a=17.62, b=243.12 — диапазон −45…+60 °C)."""
    if t is None or h is None or h <= 0:
        return None
    a, b = 17.62, 243.12
    gamma = math.log(min(h, 100) / 100.0) + a * t / (b + t)
    return round(b * gamma / (a - gamma), 1)


def sun_times(date_local: datetime.date) -> Tuple[str, str]:
    """Восход/закат (местное HH:MM) по NOAA-приближению для CITY_LAT/LON."""
    day_of_year = date_local.timetuple().tm_yday
    gamma = math.pi / 180 * 360 / 365 * (day_of_year - 1)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                       - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
    decl = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
            - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
            - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
    zen = math.radians(90.833)
    cos_ha = (math.cos(zen) / (math.cos(math.radians(CITY_LAT)) * math.cos(decl))
              - math.tan(math.radians(CITY_LAT)) * math.tan(decl))
    cos_ha = max(-1.0, min(1.0, cos_ha))
    ha_deg = math.degrees(math.acos(cos_ha))
    sunrise_utc_min = 720 - 4 * (CITY_LON + ha_deg) - eqtime
    sunset_utc_min = 720 - 4 * (CITY_LON - ha_deg) - eqtime

    def fmt(minutes: float) -> str:
        local_min = (minutes % 1440) + 180  # UTC+3
        h, m = int(local_min) // 60 % 24, int(local_min) % 60
        return f"{h:02d}:{m:02d}"

    return fmt(sunrise_utc_min), fmt(sunset_utc_min)


def human_dh(seconds: float) -> str:
    """Uptime по-человечески: 'N сут M ч K мин'."""
    s = int(max(seconds, 0))
    days, s = divmod(s, 86400)
    hours, s = divmod(s, 3600)
    minutes = s // 60
    if days:
        return f"{days} сут {hours} ч"
    if hours:
        return f"{hours} ч {minutes} мин"
    return f"{minutes} мин"


def fmt_num(v) -> str:
    """Число или прочерк (для NaN/False-значений давления и пр.)."""
    if v is None:
        return "—"
    try:
        fval = float(v)
        if math.isnan(fval):
            return "—"
    except (TypeError, ValueError):
        return "—"
    s = str(v)
    return s if '.' in s else f"{s}.0" if isinstance(v, float) else s

# --- FLASK: приём данных и алертов от станции ---
def bad_value(v: float, rng: Tuple[float, float]) -> bool:
    # Сюда попадают и NaN: сравнения с NaN дают False, значит not() = True
    return not (rng[0] <= v <= rng[1])


@app.route('/update')
def update():
    """Эндпоинт приёма данных: /update?key=<SENSOR_KEY>&t=<temp>&h=<hum>&p=<pres>"""
    if request.args.get('key') != SENSOR_KEY:
        logger.warning("🚫 Отказ /update: неверный ключ с %s", request.remote_addr)
        reject_stamps.append(time.time())
        return "Forbidden", 403
    try:
        t = float(request.args.get('t'))
        h = float(request.args.get('h'))
        p = float(request.args.get('p'))
    except (TypeError, ValueError):
        logger.warning("🚫 Отказ /update: нечисловые параметры с %s", request.remote_addr)
        reject_stamps.append(time.time())
        return "Bad values", 400

    if bad_value(t, TEMP_RANGE) or bad_value(h, HUM_RANGE) or bad_value(p, PRES_RANGE):
        logger.warning("🚫 Отказ /update: значения вне диапазона t=%s h=%s p=%s", t, h, p)
        reject_stamps.append(time.time())
        return "Values out of range", 400

    try:
        with sqlite3.connect(DB_NAME, timeout=10) as conn:
            conn.execute("PRAGMA busy_timeout=10000;")
            conn.execute("INSERT INTO weather_data (temp, hum, pres) VALUES (?, ?, ?)", (t, h, p))
            conn.commit()
        return "OK", 200
    except Exception as e:
        logger.error(f"Flask /update error: {e}")
        return str(e), 500


@app.route('/alert')
def esp_alert():
    """Труба алертов из прошивки ESP32 (будущий RPM-мониторинг и прочее):
    GET /alert?key=<SENSOR_KEY>&text=<сообщение> — бот рассылает всем пользователям."""
    if request.args.get('key') != SENSOR_KEY:
        logger.warning("🚫 Отказ /alert: неверный ключ с %s", request.remote_addr)
        return "Forbidden", 403
    text = (request.args.get('text') or '').strip()
    if not text:
        return "Empty", 400
    if not alert_allowed(f'esp:{text[:80]}'):
        logger.info("Алерт от ESP подавлен анти-флудом: %s", text[:80])
        return "OK (throttled)", 200
    # Кладём в очередь, разошлёт asyncio-watchdog в основном loop'е
    esp_alert_queue.append(text[:ESP_ALERT_MAX_LEN])
    return "OK", 200


async def esp_alert_watcher() -> None:
    """Разбирает очереди алертов (Flask-поток не может лезть в чужой loop):
    esp_alert_queue — от ESP с префиксом, web_broadcast_queue — рассылки веб-админки."""
    while True:
        try:
            while esp_alert_queue:
                text = esp_alert_queue.popleft()
                await broadcast(f"📡 От станции: {text}")
                logger.info("Алерт от ESP разослан: %s", text[:80])
            while web_broadcast_queue:
                text = web_broadcast_queue.popleft()
                sent = await broadcast(text)
                logger.info("Рассылка веб-админки отправлена (%d получ.): %s", sent, text[:80])
        except Exception:
            logger.exception("Ошибка в esp_alert_watcher")
        await asyncio.sleep(2)  # очереди должны опустошаться быстро, не раз в 5 минут

# --- ФОНОВЫЕ ПРОЦЕССЫ ---
esp_alert_queue: deque = deque(maxlen=20)


@app.route('/health')
def health():
    """Мини-эндпоинт для ручной проверки живости: /health"""
    return "OK", 200


def _parse_db_ts(ts: str) -> Optional[datetime.datetime]:
    try:
        return datetime.datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
    except (TypeError, ValueError):
        return None


async def silence_watcher() -> None:
    """Watchdog «Станция молчит» + «Станция вернулась» на стороне бота.

    Мёртвая станция не сообщит о себе сама, поэтому смотрим на MAX(timestamp).
    """
    global silence_flag
    while True:
        try:
            row = await execute_query("SELECT MAX(timestamp) FROM weather_data", fetch_one=True)
            if row and row[0]:
                last = _parse_db_ts(row[0])
                if last:
                    mins_ago = (datetime.datetime.utcnow() - last).total_seconds() / 60.0
                    if mins_ago > SILENCE_LIMIT_MIN:
                        if not silence_flag and alert_allowed('silence'):
                            silence_flag = True
                            txt = (f"🔇 Станция не отвечает: последний замер "
                                   f"{int(mins_ago)} мин назад (> {SILENCE_LIMIT_MIN} мин).")
                            await broadcast(txt)
                            logger.warning("Алерт «станция молчит»: %.0f мин", mins_ago)
                    elif silence_flag:
                        silence_flag = False
                        _last_alert_at.pop('silence', None)
                        await broadcast("🟢 Станция вернулась в онлайн, данные снова пишутся.")
                        logger.info("Станция вернулась после простоя")
        except Exception:
            logger.exception("Ошибка в silence_watcher")
        await asyncio.sleep(CHECK_INTERVAL_S)


async def sensor_error_watcher() -> None:
    """Алерт «ошибка датчика»: станция шумит отказами /update (3+ за 15 минут)."""
    while True:
        try:
            now = time.time()
            recent = [s for s in reject_stamps if now - s <= 15 * 60]
            reject_stamps.clear()
            reject_stamps.extend(recent)
            if len(recent) >= 3 and alert_allowed('sensor_error'):
                txt = (f"⚠️ Станция передаёт некорректные данные: {len(recent)} отказов "
                       f"за 15 мин (вне диапазона / неверный ключ).")
                await broadcast(txt)
                logger.warning("Алерт «ошибка датчика»: %d отказов/15мин", len(recent))
        except Exception:
            logger.exception("Ошибка в sensor_error_watcher")
        await asyncio.sleep(CHECK_INTERVAL_S)


async def temp_jump_watcher() -> None:
    """Алерт «резкий скачок температуры»: дельта средних 30-минутных окон > JUMP_LIMIT."""
    while True:
        try:
            now_stats = await execute_query(
                "SELECT AVG(temp) FROM weather_data "
                "WHERE timestamp > datetime('now', '-30 minutes') AND temp IS NOT NULL",
                fetch_one=True)
            prev_stats = await execute_query(
                "SELECT AVG(temp) FROM weather_data "
                "WHERE timestamp BETWEEN datetime('now', '-60 minutes') "
                "AND datetime('now', '-30 minutes') AND temp IS NOT NULL",
                fetch_one=True)
            if now_stats and prev_stats and now_stats[0] is not None and prev_stats[0] is not None:
                delta = now_stats[0] - prev_stats[0]
                if abs(delta) >= JUMP_LIMIT_C and alert_allowed('tjump', JUMP_COOLDOWN_S):
                    arrow = "⬇️" if delta < 0 else "⬆️"
                    txt = (f"{arrow} Резкое изменение температуры: "
                           f"{delta:+.1f} °C за последние ~30 мин "
                           f"(было {round(prev_stats[0], 1)}, стало {round(now_stats[0], 1)}).")
                    await broadcast(txt)
                    logger.warning("Алерт «скачок T»: %+.1f °C/30мин", delta)
        except Exception:
            logger.exception("Ошибка в temp_jump_watcher")
        await asyncio.sleep(TREND_CHECK_INTERVAL_S)


async def frost_watcher() -> None:
    """Морозный алерт: свежая температура ниже FROST_THRESHOLD_C."""
    while True:
        try:
            row = await execute_query(
                "SELECT temp FROM weather_data ORDER BY id DESC LIMIT 1", fetch_one=True)
            if row and row[0] is not None and row[0] <= FROST_THRESHOLD_C:
                if alert_allowed('frost', FROST_COOLDOWN_S):
                    await broadcast(f"🥶 Мороз!: текущая температура {round(row[0], 1)} °C "
                                    f"(ниже {FROST_THRESHOLD_C} °C).")
                    logger.warning("Морозный алерт: %.1f °C", row[0])
        except Exception:
            logger.exception("Ошибка в frost_watcher")
        await asyncio.sleep(CHECK_INTERVAL_S)


def _local_now() -> datetime.datetime:
    return datetime.datetime.utcnow() + LOCAL_TZ_SHIFT


async def daily_digest_loop() -> None:
    """Ежедневный дайджест в DIGEST_HOUR по местному (UTC+3)."""
    while True:
        now = _local_now()
        target = now.replace(hour=DIGEST_HOUR, minute=0, second=0, microsecond=0)
        if target <= now:
            target += datetime.timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        try:
            if alert_allowed('digest'):
                stats = await execute_query(
                    f"""SELECT COUNT(*), MIN(temp), MAX(temp), MIN(hum), MAX(hum)
                        FROM weather_data
                        WHERE date(timestamp, '{TIMEZONE_OFFSET}') = date('now', '{TIMEZONE_OFFSET}')""",
                    fetch_one=True)
                if not stats or not stats[0]:
                    await broadcast("📝 **Ежедневный дайджест**: данных за сутки не было. "
                                    "Проверь станцию.")
                    continue
                uptime = human_dh(time.time() - BOT_START_TIME)
                txt = (f"📝 **Ежедневный дайджест**\n━━━━━━━━━━━━\n"
                       f"🌡 Температура: {round(stats[1], 1)}…{round(stats[2], 1)} °C\n"
                       f"💧 Влажность: {round(stats[3], 1)}…{round(stats[4], 1)} %\n"
                       f"📥 Записей за сутки: {stats[0]}\n"
                       f"⏱ Uptime бота: {uptime}")
                sent = await broadcast(txt)
                logger.info("Ежедневный дайджест отправлен (%d получ.)", sent)
        except Exception:
            logger.exception("Ошибка в daily_digest_loop")


def backup_db_sync() -> Optional[str]:
    """Дневная копия БД через sqlite3-backup API (безопасно при WAL/активной записи)."""
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        stamp = datetime.datetime.utcnow().strftime('%Y%m%d')
        dst_name = os.path.join(BACKUP_DIR, f"weather_{stamp}.db")

        src = sqlite3.connect(DB_NAME)
        dst = sqlite3.connect(dst_name)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()

        # Ротация: оставляем последние BACKUP_KEEP копий
        backups = sorted(
            f for f in os.listdir(BACKUP_DIR)
            if f.startswith("weather_") and f.endswith(".db")
        )
        for old in backups[:-BACKUP_KEEP]:
            try:
                os.remove(os.path.join(BACKUP_DIR, old))
            except OSError as e:
                logger.error("Не удалось удалить старый бэкап: %s", e)
        return dst_name
    except Exception as e:
        logger.error("Бэкап БД не удался: %s", e)
        return None


async def backup_loop() -> None:
    while True:
        await asyncio.sleep(BACKUP_INTERVAL_S)
        name = await asyncio.to_thread(backup_db_sync)
        if name:
            logger.info("Ночной бэкап сделан: %s", name)

# --- СВОДКА ---
async def get_daily_summary_text() -> str:
    sunrise, sunset = sun_times(_local_now().date())
    if TEST_MODE:
        return get_test_summary() + f"\n\n🌅 Восход: {sunrise} | 🌇 Закат: {sunset}"

    query = f"""
        SELECT
            CASE
                WHEN strftime('%H', datetime(timestamp, '{TIMEZONE_OFFSET}')) BETWEEN '05' AND '11' THEN 'Утро'
                WHEN strftime('%H', datetime(timestamp, '{TIMEZONE_OFFSET}')) BETWEEN '12' AND '16' THEN 'День'
                WHEN strftime('%H', datetime(timestamp, '{TIMEZONE_OFFSET}')) BETWEEN '17' AND '21' THEN 'Вечер'
                ELSE 'Ночь'
            END as period,
            MIN(temp), MAX(temp), MIN(timestamp)
        FROM weather_data
        WHERE date(timestamp, '{TIMEZONE_OFFSET}') = date('now', '{TIMEZONE_OFFSET}')
        GROUP BY period ORDER BY MIN(timestamp) ASC
    """
    rows = await execute_query(query, fetch=True)

    lines = ["📅 **Сводка за сегодня:**"]
    if rows:
        for row in rows:
            icon = "🌙" if row[0] == 'Ночь' else "🌅" if row[0] == 'Утро' else "☀️" if row[0] == 'День' else "🌆"
            lines.append(f"{icon} {row[0]}: {round(row[1], 1)}°C ... {round(row[2], 1)}°C")
    else:
        lines.append("Записей за сегодня ещё нет.")
    lines.append(f"\n🌅 Восход: {sunrise} | 🌇 Закат: {sunset} (Солигорск)")
    return "\n".join(lines)

# --- ГРАФИКИ ---
def _create_chart_sync(rows: List[Tuple], mode: str, label: str) -> Optional[io.BytesIO]:
    with _PLT_LOCK:
        return _create_chart_locked(rows, mode, label)


def _create_chart_locked(rows: List[Tuple], mode: str, label: str) -> Optional[io.BytesIO]:
    if not rows: return None

    plt.style.use('default')
    fig, ax = plt.subplots(figsize=(12, 6), dpi=120)

    bg_color = '#0f1419'
    text_color = '#c0c8d1'
    grid_color = '#1e2734'

    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(bg_color)

    now_day = datetime.datetime.now().strftime('%d')
    ax2 = None

    if mode == 'daily':
        labels = [f"{'Сег' if r[0] == now_day else 'Вчр'} {r[1]}" for r in rows]
        data = [round(r[2], 1) for r in rows]
        line_color = '#0ea5e9'  # небесно-голубой
        # Влажность второй линией (правая ось), если она есть в данных
        hum_col = None
        for r in rows:
            if len(r) >= 4 and r[3] is not None:
                hum_col = 3
                break
        if hum_col is not None:
            ax2 = ax.twinx()
            ax2.plot(labels, [round(r[3], 1) for r in rows], color='#34d399',
                     linewidth=1.6, linestyle='--', alpha=0.85, zorder=2)
            ax2.set_ylabel('Влажность, %', color='#34d399')
            ax2.tick_params(axis='y', colors='#34d399')
            ax2.set_ylim(0, 100)
            ax2.spines['right'].set_color('#1e2734')
    else:
        labels, data = [r[0] for r in rows], [round(r[1], 1) for r in rows]
        # '#a3e635' — лаймовый, чтобы точка росы не путалась с температурой
        line_color = '#a3e635' if mode == 'dew' else '#2563eb'

    ax.plot(labels, data, color=line_color, linewidth=3, zorder=3,
            solid_capstyle='round', solid_joinstyle='round')
    ax.fill_between(labels, min(data) - 5, data, color=line_color, alpha=0.15)

    min_val, max_val = min(data), max(data)
    min_idx = data.index(min_val)
    max_idx = data.index(max_val)
    unit = "" if mode == 'dew' else "°C"

    ax.annotate(f"▼ {min_val}{unit}", (labels[min_idx], min_val), xytext=(0, -15),
                textcoords="offset points", ha='center', color='#f87171', fontsize=9)
    ax.annotate(f"▲ {max_val}{unit}", (labels[max_idx], max_val), xytext=(0, 10),
                textcoords="offset points", ha='center', color='#34d399', fontsize=9)

    ax.spines['top'].set_visible(False)
    ax.spines['left'].set_color(grid_color)
    ax.spines['bottom'].set_color(grid_color)
    if ax2 is None:
        ax.spines['right'].set_visible(False)
    else:
        # правая рамка занята осью влажности
        pass

    ax.tick_params(axis='x', colors=text_color, rotation=45, labelsize=9)
    ax.tick_params(axis='y', colors=text_color, labelsize=9)

    ax.grid(True, color=grid_color, linestyle=':', linewidth=0.8, alpha=0.8)
    ax.set_axisbelow(True)

    plt.title(f"Солигорск: {label}", color=text_color, pad=15, fontsize=14, weight='bold')
    if len(labels) > 48:
        ax.xaxis.set_major_locator(plt.MaxNLocator(40))
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png', facecolor=bg_color)
    buf.seek(0)
    plt.close(fig)
    return buf


def _create_empty_chart_sync(label: str) -> io.BytesIO:
    with _PLT_LOCK:
        return _create_empty_chart_locked(label)


def _create_empty_chart_locked(label: str) -> io.BytesIO:
    """Заглушка «нет данных» в палитре графиков, чтобы <img> не выглядел сломанным."""
    plt.style.use('default')
    fig, ax = plt.subplots(figsize=(12, 6), dpi=120)
    bg_color = '#0f1419'
    text_color = '#c0c8d1'
    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(bg_color)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_color('#1e2734')
    ax.text(0.5, 0.56, "Нет данных за период", ha='center', va='center',
            color=text_color, fontsize=16, weight='bold', transform=ax.transAxes)
    ax.text(0.5, 0.46, "включи «Тестовые графики» или дождись замеров станции",
            ha='center', va='center', color='#7a8590', fontsize=10, transform=ax.transAxes)
    ax.set_title(label, color=text_color, pad=15, fontsize=14, weight='bold')
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', facecolor=bg_color)
    buf.seek(0)
    plt.close(fig)
    return buf


async def create_chart(mode: str, label: str) -> Optional[io.BytesIO]:
    if TEST_MODE:
        rows = get_test_chart_data(mode)
    elif mode == 'daily':
        rows = await execute_query(f"""
            SELECT
                strftime('%d', datetime(timestamp, '{TIMEZONE_OFFSET}')) as d,
                strftime('%H:00', datetime(timestamp, '{TIMEZONE_OFFSET}')) as h,
                AVG(temp), AVG(hum), MIN(timestamp) as ts
            FROM weather_data WHERE timestamp > datetime('now', '-24 hours')
            GROUP BY d, h ORDER BY ts ASC
        """, fetch=True)
    elif mode == 'dew':
        rows = await execute_query(f"""
            SELECT strftime('%d.%m', datetime(timestamp, '{TIMEZONE_OFFSET}')) as d,
                   AVG(temp), AVG(hum)
            FROM weather_data
            WHERE timestamp > datetime('now', '-7 days') AND temp IS NOT NULL AND hum IS NOT NULL
            GROUP BY d ORDER BY MIN(timestamp) ASC
        """, fetch=True)
        # Пересчитываем средние за день в точку росы
        rows = [(r[0], dew_point(r[1], r[2])) for r in rows] if rows else []
        rows = [r for r in rows if r[1] is not None]
    elif mode == 'weekly':
        rows = await execute_query(f"""
            SELECT strftime('%d.%m', datetime(timestamp, '{TIMEZONE_OFFSET}')) as d, AVG(temp)
            FROM weather_data WHERE timestamp > datetime('now', '-7 days')
            GROUP BY d ORDER BY MIN(timestamp) ASC
        """, fetch=True)
    else:  # monthly
        rows = await execute_query(f"""
            SELECT strftime('%d.%m', datetime(timestamp, '{TIMEZONE_OFFSET}')) as d, AVG(temp)
            FROM weather_data WHERE timestamp > datetime('now', '-30 days')
            GROUP BY d ORDER BY MIN(timestamp) ASC
        """, fetch=True)

    if not rows: return None

    return await asyncio.to_thread(_create_chart_sync, rows, mode, label)

# --- МИНИМАЛЬНЫЙ XLSX (без openpyxl, чистым zipfile) ---
def _xml_escape(s: str) -> str:
    return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


def _col_letter(idx: int) -> str:
    """8 -> 'I' (1-based)."""
    letters = ''
    while idx:
        idx, rem = divmod(idx - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def make_xlsx_bytes(header: List[str], rows: List[Tuple]) -> io.BytesIO:
    """Собирает настоящий .xlsx (Excel открывает) без внешних библиотек."""
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
          '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
          '</Types>')

    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" '
                 'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
                 'Target="xl/workbook.xml"/></Relationships>')

    wb_xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
              'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
              '<sheets><sheet name="Данные" sheetId="1" r:id="rId1"/></sheets></workbook>')

    wb_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
               '<Relationship Id="rId1" '
               'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
               'Target="worksheets/sheet1.xml"/></Relationships>')

    body = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetData>']

    def row_xml(row_values: Tuple, row_no: int) -> str:
        parts = []
        for i, v in enumerate(row_values, 1):
            ref = f"{_col_letter(i)}{row_no}"
            if v is None or (isinstance(v, float) and math.isnan(v)):
                parts.append(f'<c r="{ref}"/>')
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                parts.append(f'<c r="{ref}"><v>{v}</v></c>')
            else:
                parts.append(f'<c t="inlineStr" r="{ref}"><is><t>{_xml_escape(str(v))}</t></is></c>')
        return f'<row r="{row_no}">{"".join(parts)}</row>'

    body.append(row_xml(tuple(header), 1))
    for n, r in enumerate(rows, 2):
        body.append(row_xml(tuple(r), n))
    body.append('</sheetData></worksheet>')

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', ct)
        z.writestr('_rels/.rels', root_rels)
        z.writestr('xl/workbook.xml', wb_xml)
        z.writestr('xl/_rels/workbook.xml.rels', wb_rels)
        z.writestr('xl/worksheets/sheet1.xml', ''.join(body))
    buf.seek(0)
    return buf

# --- ГЛОБАЛЬНЫЙ ОБРАБОТЧИК ОШИБОК ---
@dp.errors()
async def on_error(update: types.Update, exception: Exception) -> bool:
    logger.exception(f"Необработанная ошибка в update {update.update_id}: {exception}")
    return True

# --- ОСНОВНЫЕ ХЕНДЛЕРЫ ---
@dp.message(F.text == "/start")
async def cmd_start(message: types.Message) -> None:
    await register_user(message.from_user.id)
    await message.answer(
        "👋 Метеостанция «Солигорск» (TestV3) готова!\n\n"
        "🌡 Погода • 📅 Сводка • 📊 Графики и рекорды • 💧 Точка росы\n"
        "Алерты: тишина / ошибка датчика / резкий скачок T / мороз / дайджест 21:00",
        reply_markup=main_kb
    )


@dp.message(F.text == "/id")
@dp.message(F.text == "🪪 Мой ID")
async def cmd_id(message: types.Message) -> None:
    await register_user(message.from_user.id)
    await message.answer(f"🆔 Твой Telegram ID: `{message.from_user.id}`", parse_mode="Markdown")


@dp.message(F.text == "/promo")
@dp.message(F.text == "ℹ️ Фичи")
async def cmd_promo(message: types.Message) -> None:
    await message.answer(
        "ℹ️ TestV3 — что есть:\n"
        "• ключ и валидация на /update — мусор в БД не попадёт\n"
        "• алерты: тишина станции, ошибка датчика, резкий скачок T, мороз,\n"
        "  дневной дайджест 21:00\n"
        "• точка росы, тренд давления, восход/закат, возраст замера\n"
        "• графики: 24ч (T+H), неделя, месяц, точка росы-неделя\n"
        "• ночные бэкапы БД + «⚡ Бэкап сейчас» файлом в чат\n"
        "• экспорт CSV и Excel (настоящий .xlsx без openpyxl)\n"
        "• /alert — труба алертов из прошивки ESP32 (для RPM-мониторинга)"
    )


@dp.message(F.text == ADMIN_PASS)
async def dev_login(message: types.Message) -> None:
    await register_user(message.from_user.id)
    await message.answer("🔓 Режим администратора.", reply_markup=get_admin_kb())


@dp.message(F.text == "Назад")
async def go_back(message: types.Message) -> None:
    await message.answer("Главное меню", reply_markup=main_kb)


async def weather_now_text() -> Optional[str]:
    res = await execute_query(
        "SELECT temp, hum, pres FROM weather_data ORDER BY id DESC LIMIT 1", fetch_one=True)
    if not res:
        return None

    # Возраст последнего замера
    row = await execute_query("SELECT MAX(timestamp) FROM weather_data", fetch_one=True)
    age_str = ""
    if row and row[0]:
        last = _parse_db_ts(row[0])
        if last:
            mins = int((datetime.datetime.utcnow() - last).total_seconds() // 60)
            age_str = f"\n⏱ Замер {human_dh(mins * 60)} назад"

    # Тренд давления за 3 часа: среднее последних 30 мин vs среднее 3-3.5ч назад
    p_now = await execute_query(
        "SELECT AVG(pres) FROM weather_data WHERE timestamp > datetime('now', '-30 minutes') "
        "AND pres IS NOT NULL", fetch_one=True)
    p_before = await execute_query(
        "SELECT AVG(pres) FROM weather_data "
        "WHERE timestamp BETWEEN datetime('now', '-210 minutes') AND datetime('now', '-180 minutes') "
        "AND pres IS NOT NULL", fetch_one=True)
    trend = ""
    if p_now and p_before and p_now[0] is not None and p_before[0] is not None:
        d = p_now[0] - p_before[0]
        if d <= -1.5:
            trend = " ⬇️ (давление падает — к непогоде)"
        elif d >= 1.5:
            trend = " ⬆️ (давление растёт — к ясному)"
        else:
            trend = " ➡️ ровно"

    dp = dew_point(res[0], res[1])
    pres_str = fmt_num(res[2])
    dew_str = f"💧 Точка росы: {dp}°C\n" if dp is not None else ""
    return (f"🌡 Температура: {res[0]}°C\n"
            f"💧 Влажность: {res[1]}%\n"
            f"☁️ Давление: {pres_str} мм{trend}\n"
            f"{dew_str}"
            f"{age_str}")


@dp.message(F.text == "Погода сейчас")
async def weather_now(message: types.Message) -> None:
    await register_user(message.from_user.id)
    if TEST_MODE:
        t, h, p = get_test_current_weather()
        dp = dew_point(t, h)
        await message.answer(f"🌡 Температура: {t}°C\n💧 Влажность: {h}%\n☁️ Давление: {p} мм\n"
                             f"💧 Точка росы: {dp}°C\n⏱ Замер: только что (TEST)")
        return
    text = await weather_now_text()
    await message.answer(text if text else "📡 Данных нет.")


@dp.message(F.text == "💧 Точка росы")
async def dew_only(message: types.Message) -> None:
    await register_user(message.from_user.id)
    if TEST_MODE:
        t, h, _ = get_test_current_weather()
        await message.answer(f"💧 Точка росы: {dew_point(t, h)}°C (TEST)")
        return
    res = await execute_query(
        "SELECT temp, hum FROM weather_data WHERE temp IS NOT NULL AND hum IS NOT NULL "
        "ORDER BY id DESC LIMIT 1", fetch_one=True)
    if not res:
        await message.answer("📡 Данных нет.")
        return
    dp = dew_point(res[0], res[1])
    hint = ""
    if dp is not None and res[0] - dp < 2.0:
        hint = "\n⚠️ T близко к точке росы — риск конденсата/инея."
    await message.answer(f"💧 Точка росы: {dp}°C\n🌡 текущая: {res[0]}°C, влажность: {res[1]}%"
                         f"{hint}")


@dp.message(F.text == "📊 Статистика")
async def quick_stats(message: types.Message) -> None:
    await register_user(message.from_user.id)
    if TEST_MODE:
        await message.answer("📊 Статистика (TEST): 24ч 5…20°C, 7д 1…22°C, 30д −3…24°C")
        return
    lines = ["📊 **Статистика:**\n"]
    for title, days in (("24 часа:", 1), ("7 дней:", 7), ("30 дней:", 30)):
        s = await execute_query(
            f"""SELECT MIN(temp), MAX(temp), AVG(temp), COUNT(*)
                FROM weather_data
                WHERE timestamp > datetime('now', '-{days} days') AND temp IS NOT NULL""",
            fetch_one=True)
        if s and s[0] is not None:
            lines.append(f"• {title} {round(s[0], 1)}…{round(s[1], 1)}°C "
                         f"(ср {round(s[2], 1)}, записей {s[3]})")
        else:
            lines.append(f"• {title} данных нет")
    await message.answer("\n".join(lines), parse_mode="Markdown")


@dp.message(F.text == "Сводка за сегодня")
async def daily_summary(message: types.Message) -> None:
    await register_user(message.from_user.id)
    text = await get_daily_summary_text()
    await message.answer(text, parse_mode="Markdown")


@dp.message(F.text == "Погода за период")
async def select_period(message: types.Message) -> None:
    await message.answer("Выберите тип графика:", reply_markup=period_kb)

# --- ХЕНДЛЕРЫ графиков ---
@dp.message(F.text.in_({"За 24 часа", "За неделю", "За месяц"}))
async def charts(message: types.Message) -> None:
    await register_user(message.from_user.id)
    mode = {'За 24 часа': ('daily', "Температура за 24ч (— влажность)"),
            'За неделю': ('weekly', "Динамика недели"),
            'За месяц': ('monthly', "Динамика месяца")}[message.text]
    buf = await create_chart(mode[0], mode[1])
    if buf:
        await message.answer_photo(BufferedInputFile(buf.read(), "chart.png"))
    else:
        await message.answer("📉 Мало данных.")


@dp.message(F.text == "Точка росы (неделя)")
async def chart_dew(message: types.Message) -> None:
    await register_user(message.from_user.id)
    buf = await create_chart('dew', "Точка росы (неделя)")
    if buf:
        await message.answer_photo(BufferedInputFile(buf.read(), "dew.png"))
    else:
        await message.answer("📉 Мало данных.")

# --- РЕКОРДЫ 24Ч ---
LIMITS = {
    "Макс °C":   ("temp", "DESC", "🔥 Максимум: `{v}°C` в `{t}`"),
    "Мин °C":    ("temp", "ASC",  "❄️ Минимум: `{v}°C` в `{t}`"),
    "Макс %":    ("hum",  "DESC", "💦 Максимум влажности: `{v}%` в `{t}`"),
    "Мин %":     ("hum",  "ASC",  "🏜 Минимум влажности: `{v}%` в `{t}`"),
    "Макс давл": ("pres", "DESC", "⬆️ Максимум давления: `{v} мм` в `{t}`"),
    "Мин давл":  ("pres", "ASC",  "⬇️ Минимум давления: `{v} мм` в `{t}`"),
}

TEST_LIMIT_MAP = {'Макс °C': 'temp_max', 'Мин °C': 'temp_min',
                  'Макс %': 'hum_max', 'Мин %': 'hum_min',
                  'Макс давл': 'pres_max', 'Мин давл': 'pres_min'}


@dp.message(F.text.in_(LIMITS.keys()))
async def show_limit(message: types.Message) -> None:
    await register_user(message.from_user.id)
    metric, order, tmpl = LIMITS[message.text]

    if TEST_MODE:
        value, ts = get_test_limit(TEST_LIMIT_MAP[message.text])
        await message.answer(tmpl.format(v=value, t=ts), parse_mode="Markdown")
        return

    res = await execute_query(
        f"""SELECT {metric}, strftime('%H:%M', datetime(timestamp, '{TIMEZONE_OFFSET}'))
            FROM weather_data
            WHERE timestamp > datetime('now', '-24 hours') AND {metric} IS NOT 'nan'
            ORDER BY {metric} {order} LIMIT 1""",
        fetch_one=True)
    if res:
        await message.answer(tmpl.format(v=res[0], t=res[1]), parse_mode="Markdown")
    else:
        await message.answer("📉 Данных за 24 часа нет.")


@dp.message(F.text == "Пределы 24ч")
async def show_limits_kb(message: types.Message) -> None:
    await message.answer("Рекорды за последние 24 часа:", reply_markup=limits_kb)

# --- ХЕНДЛЕРЫ РАЗРАБОТЧИКА ---
@dp.message(F.text == "📊 Статус системы")
async def sys_status(message: types.Message) -> None:
    disk = psutil.disk_usage(DISK_PATH)
    stats = await execute_query(
        f"SELECT COUNT(*), IFNULL(datetime(MAX(timestamp), '{TIMEZONE_OFFSET}'), 'Нет') FROM weather_data",
        fetch_one=True)
    db_size = os.path.getsize(DB_NAME) / 1024 / 1024
    backup_count = len([f for f in os.listdir(BACKUP_DIR) if f.endswith('.db')]) \
        if os.path.isdir(BACKUP_DIR) else 0
    mem = psutil.virtual_memory()
    now = time.time()
    rejects_24h = len([s for s in reject_stamps if now - s <= 24 * 3600])
    await message.answer(
        f"🖥 **System Status (TestV3)**\n━━━━━━━━━━━━\n"
        f"📅 Последняя запись: `{stats[1]}`\n"
        f"📈 Всего записей: `{stats[0]}`\n"
        f"🚫 Отказов /update за 24ч: `{rejects_24h}`\n"
        f"💾 Диск свободно: `{round(disk.free / 1024**3, 2)} GB`\n"
        f"🧠 RAM занято: `{mem.percent}%`\n"
        f"🗄 БД: `{round(db_size, 1)} MB`, бэкапов: `{backup_count}`\n"
        f"⏱ Uptime бота: `{human_dh(time.time() - BOT_START_TIME)}`\n"
        f"🏁 Бот стартовал: `{BOT_STARTED_AT_STR}`\n"
        f"🔇 Watchdog: `{SILENCE_LIMIT_MIN} мин`\n"
        f"🥶 Порог мороза: `{FROST_THRESHOLD_C}°C` ⬆️ скачок: `{JUMP_LIMIT_C}°C/30мин`\n"
        f"🧪 Test Mode: `{'ВКЛ' if TEST_MODE else 'ВЫКЛ'}`",
        parse_mode="Markdown")


@dp.message(F.text == "📈 Аналитика")
async def analytics(message: types.Message) -> None:
    active_1h = await execute_query(
        f"SELECT COUNT(*) FROM users WHERE last_active > datetime('now', '{TIMEZONE_OFFSET}', '-1 hour')",
        fetch_one=True)
    total_users = await execute_query("SELECT COUNT(*) FROM users", fetch_one=True)
    sensor_1h = await execute_query(
        "SELECT COUNT(*) FROM weather_data WHERE timestamp > datetime('now', '-1 hour')", fetch_one=True)
    sensor_24h = await execute_query(
        "SELECT COUNT(*) FROM weather_data WHERE timestamp > datetime('now', '-24 hours')", fetch_one=True)
    await message.answer(
        f"📈 **Аналитика бота:**\n━━━━━━━━━━━━\n"
        f"👥 Всего пользователей: `{total_users[0] if total_users else 0}`\n"
        f"⏱ Активны за 1 час: `{active_1h[0] if active_1h else 0}`\n"
        f"📡 От станции за 1ч: `{sensor_1h[0] if sensor_1h else 0}`\n"
        f"📡 От станции за 24ч: `{sensor_24h[0] if sensor_24h else 0}`",
        parse_mode="Markdown")


@dp.message(F.text == "🌡 CPU и RAM")
async def cpu_ram(message: types.Message) -> None:
    lines = []
    try:
        # Стандартный путь для одноплаток на Linux (ARM)
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            temp_cpu = round(int(f.read().strip()) / 1000.0, 1)
        status = "❄️ Норма" if temp_cpu < 50 else "🟡 Тепло" if temp_cpu < 70 else "🔴 Опасно!"
        lines.append(f"🌡 CPU: `{temp_cpu}°C` {status}")
    except Exception as e:
        logger.error(f"Ошибка чтения температуры CPU: {e}")
        lines.append("🌡 CPU: ❌ не удалось получить")
    ram = psutil.virtual_memory()
    lines.append(f"🧠 RAM: `{ram.percent}%` "
                 f"({round(ram.used / 1024**3, 1)} из {round(ram.total / 1024**3, 1)} GB)")
    await message.answer("\n".join(lines), parse_mode="Markdown")


@dp.message(F.text == "📦 Экспорт CSV")
async def export_csv(message: types.Message) -> None:
    rows = await execute_query(
        f"""SELECT id, datetime(timestamp, '{TIMEZONE_OFFSET}'), temp, hum, pres
            FROM weather_data WHERE timestamp > datetime('now', '-7 days') ORDER BY id ASC""",
        fetch=True)
    if not rows:
        await message.answer("📭 Данных за 7 дней нет.")
        return
    buf = io.BytesIO()
    buf.write("id;дата-время (UTC+3);темп °C;влажность %;давление\r\n".encode("utf-8-sig"))
    for r in rows:
        buf.write(f"{r[0]};{r[1]};{r[2]};{r[3]};{r[4]}\r\n".encode("utf-8"))
    buf.seek(0)
    await message.answer_document(
        BufferedInputFile(buf.read(), "weather_7d.csv"),
        caption=f"📦 Данные за 7 дней ({len(rows)} записей)")


@dp.message(F.text == "📊 Экспорт Excel")
async def export_excel(message: types.Message) -> None:
    rows = await execute_query(
        f"""SELECT id, datetime(timestamp, '{TIMEZONE_OFFSET}'), temp, hum, pres
            FROM weather_data WHERE timestamp > datetime('now', '-7 days') ORDER BY id ASC""",
        fetch=True)
    if not rows:
        await message.answer("📭 Данных за 7 дней нет.")
        return
    data = [(r[0], r[1], r[2], r[3], fmt_num(r[4])) for r in rows]
    buf = await asyncio.to_thread(
        make_xlsx_bytes, ["id", "дата-время (UTC+3)", "Температура °C", "Влажность %", "Давление"], data)
    await message.answer_document(
        BufferedInputFile(buf.read(), "weather_7d.xlsx"),
        caption=f"📊 Excel за 7 дней ({len(rows)} записей)")


@dp.message(F.text == "💾 Бэкап сейчас")
async def backup_now(message: types.Message) -> None:
    await message.answer("💾 Делаю бэкап...")
    name = await asyncio.to_thread(backup_db_sync)
    if not name:
        await message.answer("❌ Бэкап не удался — смотри логи.")
        return
    try:
        with open(name, "rb") as f:
            await message.answer_document(
                BufferedInputFile(f.read(), os.path.basename(name)),
                caption="💾 Свежая копия БД (файл также сохранён в backups/).")
    except Exception as e:
        logger.error("Не удалось отправить бэкап: %s", e)
        await message.answer(f"💾 Бэкап создан ({os.path.basename(name)}), "
                             f"но отправить файлом не вышло: {e}")


@dp.message(F.text == "🕒 Последние данные")
async def last_data(message: types.Message) -> None:
    rows = await execute_query(
        f"SELECT datetime(timestamp, '{TIMEZONE_OFFSET}'), temp, hum, pres FROM weather_data "
        "ORDER BY id DESC LIMIT 5", fetch=True)
    if rows:
        text = "🕒 Последние 5 записей в БД:\n\n"
        for r in rows:
            text += f"`{r[0]}` | {r[1]}°C, {r[2]}%, {fmt_num(r[3])}мм\n"
        await message.answer(text, parse_mode="Markdown")
    else:
        await message.answer("База данных пуста.")


@dp.message(F.text == "✍️ Внести данные")
async def manual_insert_start(message: types.Message, state: FSMContext) -> None:
    await message.answer(
        "✍️ Отправьте данные в формате: `Темп Влажность Давление`\n"
        "Например: `25.5 60 745`\n\nДля отмены напишите 'Отмена'.",
        parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
    await state.set_state(DevStates.waiting_for_manual_data)


@dp.message(DevStates.waiting_for_manual_data, F.text == "Отмена")
async def manual_insert_cancel(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❌ Ввод отменен.", reply_markup=get_admin_kb())


@dp.message(DevStates.waiting_for_manual_data)
async def manual_insert_process(message: types.Message, state: FSMContext) -> None:
    try:
        parts = message.text.split()
        if len(parts) != 3:
            raise ValueError("Неверное количество аргументов")

        t, h, p = float(parts[0]), float(parts[1]), float(parts[2])
        if bad_value(t, TEMP_RANGE) or bad_value(h, HUM_RANGE) or bad_value(p, PRES_RANGE):
            raise ValueError("Значения вне допустимых диапазонов")

        await execute_query("INSERT INTO weather_data (temp, hum, pres) VALUES (?, ?, ?)", (t, h, p))
        await state.clear()
        await message.answer(
            f"✅ Данные `{t}°C, {h}%, {p}мм` успешно добавлены в БД!",
            parse_mode="Markdown", reply_markup=get_admin_kb())
    except Exception as e:
        await message.answer(
            f"❌ Ошибка формата: `{e}`. Попробуй еще раз или напиши 'Отмена'.",
            parse_mode="Markdown")


@dp.message(F.text == "🛠 Тех. перерыв")
async def tech_break(message: types.Message) -> None:
    await message.answer("⚠️ Начинаю рассылку...")
    count = await broadcast("⚠️Внимание! Технический перерыв")
    await message.answer(f"✅ Рассылка завершена. Отправлено: {count} польз.")


@dp.message(F.text == "✅ Возобновить")
async def resume_work(message: types.Message) -> None:
    await message.answer("🟢 Начинаю рассылку...")
    count = await broadcast("✅ Технический перерыв закончен")
    await message.answer(f"✅ Рассылка завершена. Отправлено: {count} польз.")


@dp.message(F.text == "🧹 Очистить БД")
async def clear_db(message: types.Message) -> None:
    # Перед чисткой — обязательный бэкап, чтобы чистку не пришлось оплакивать
    name = backup_db_sync()
    await execute_query("DELETE FROM weather_data")
    await message.answer(f"🗑 База очищена.{(' Резерв: ' + name) if name else ''}")


@dp.message(F.text.in_({"🧪 Тест без БД: ВЫКЛ", "🧪 Тест без БД: ВКЛ"}))
async def toggle_test_mode(message: types.Message) -> None:
    global TEST_MODE
    TEST_MODE = not TEST_MODE
    await message.answer(
        f"🧪 Тестовый режим {'ВКЛЮЧЕН' if TEST_MODE else 'ВЫКЛЮЧЕН'}.",
        reply_markup=get_admin_kb())


@dp.message(F.text == "🚪 Выход")
async def exit_admin(message: types.Message) -> None:
    await message.answer("Выход в главное меню", reply_markup=main_kb)

# --- ВЕБ-АДМИНКА (страница в браузере; тот же Flask-процесс, что /update) ---
# Авторизация по ADMIN_PASS, сессия — кукушка ws_session (HttpOnly, 12 часов).
# Порт общий с /update: TestV3 слушает 5002. ВАЖНО: это plain HTTP без TLS —
# предназначено для локальной сети; наружу не выставлять без reverse-proxy.

def _web_query(query: str, params: Tuple = ()) -> list:
    """Синхронный запрос для веб-админки (она в Flask-потоке, свой sqlite3)."""
    with sqlite3.connect(DB_NAME) as conn:
        return conn.execute(query, params).fetchall()


def _new_web_session() -> str:
    token = os.urandom(24).hex()
    now = time.time()
    WEB_SESSIONS[token] = now + WEB_SESSION_TTL_S
    for k, exp in list(WEB_SESSIONS.items()):
        if exp < now:
            WEB_SESSIONS.pop(k, None)
    return token


def _web_is_admin() -> bool:
    exp = WEB_SESSIONS.get(request.cookies.get(ADMIN_COOKIE, ""))
    return bool(exp and exp > time.time())


def _station_state():
    """(последний замер dt, возраст в минутах, онлайн ли станция)."""
    row = _web_query("SELECT MAX(timestamp) FROM weather_data")
    last = _parse_db_ts(row[0][0]) if row and row[0] else None
    if not last:
        return None, None, False
    age_min = (datetime.datetime.utcnow() - last).total_seconds() / 60.0
    return last, age_min, age_min <= SILENCE_LIMIT_MIN


def _common_ctx(active: str) -> dict:
    """Общий контекст для всех страниц (сайдбар в base.html)."""
    _, age_min, online = _station_state()
    users_total = _web_query("SELECT COUNT(*) FROM users")[0][0]
    return {
        'active': active,
        'uptime': human_dh(time.time() - BOT_START_TIME),
        'test_mode': TEST_MODE,
        'station_online': online,
        'station_age': human_dh((age_min or 0) * 60) if age_min is not None else '—',
        'users_total': users_total,
        'bot_started': BOT_STARTED_AT_STR,
    }


def _range_stats(days: int):
    r = _web_query(
        f"SELECT MIN(temp), MAX(temp), AVG(temp), COUNT(*) FROM weather_data "
        f"WHERE timestamp > datetime('now', '-{days} days') AND temp IS NOT NULL")
    return r[0] if r else (None, None, None, 0)


@app.route('/admin', methods=['GET', 'POST'])
def admin_site():
    if request.method == 'POST':
        if request.form.get('password', '') == ADMIN_PASS:
            token = _new_web_session()
            resp = redirect('/admin', code=303)
            resp.set_cookie(ADMIN_COOKIE, token, max_age=WEB_SESSION_TTL_S,
                            httponly=True, samesite='Lax')
            logger.info("Вход в веб-админку с %s", request.remote_addr)
            return resp
        return redirect('/admin', code=303)

    if not _web_is_admin():
        return render_template('login.html')

    ctx = _common_ctx('dashboard')
    total, last_ts = _web_query(
        f"SELECT COUNT(*), IFNULL(datetime(MAX(timestamp), '{TIMEZONE_OFFSET}'), '—') FROM weather_data")[0]
    sensor_24h = _web_query(
        "SELECT COUNT(*) FROM weather_data WHERE timestamp > datetime('now', '-24 hours')")[0][0]
    users_total, users_blocked = _web_query(
        "SELECT COUNT(*), IFNULL(SUM(IFNULL(blocked,0)), 0) FROM users")[0]
    active_1h = _web_query(
        f"SELECT COUNT(*) FROM users WHERE last_active > datetime('now', '{TIMEZONE_OFFSET}', '-1 hour')")[0][0]
    db_size_mb = os.path.getsize(DB_NAME) / 1024 / 1024
    rejects_24h = len([s for s in reject_stamps if time.time() - s <= 24 * 3600])

    return render_template(
        'dashboard.html', **ctx,
        total=total, last_ts=last_ts, sensor_24h=sensor_24h,
        users_blocked=users_blocked, active_1h=active_1h,
        db_size_mb=db_size_mb, rejects_24h=rejects_24h,
        s24=_range_stats(1), s7=_range_stats(7), s30=_range_stats(30),
        chart_demo=request.args.get('demo') == '1',
        bust=int(time.time()))


@app.route('/admin/users')
def admin_users_page():
    if not _web_is_admin():
        return redirect('/admin', code=303)
    user_rows = _web_query(
        f"""SELECT user_id,
                   IFNULL(datetime(last_active, '{TIMEZONE_OFFSET}'), '—'),
                   IFNULL(blocked, 0)
            FROM users
            ORDER BY IFNULL(blocked, 0) DESC, last_active IS NULL, last_active DESC
            LIMIT 500""")
    users = [{'uid': int(uid), 'act': act, 'blocked': int(blocked or 0)}
             for uid, act, blocked in user_rows]
    return render_template('users.html', **_common_ctx('users'), users=users)


@app.route('/admin/data')
def admin_data_page():
    if not _web_is_admin():
        return redirect('/admin', code=303)
    records_raw = _web_query(
        f"""SELECT id, timestamp, datetime(timestamp, '{TIMEZONE_OFFSET}'), temp, hum, pres
            FROM weather_data ORDER BY id DESC LIMIT 200""")
    records = [{'id': r[0],
                'bad': bool(r[1] and r[1] >= BAD_DATA_FROM),
                'ts': r[2], 't': r[3], 'h': r[4], 'p': fmt_num(r[5])}
               for r in (records_raw or [])]
    return render_template('data.html', **_common_ctx('data'), records=records)


@app.route('/admin/backups')
def admin_backups_page():
    if not _web_is_admin():
        return redirect('/admin', code=303)
    items = []
    if os.path.isdir(BACKUP_DIR):
        for f in sorted(os.listdir(BACKUP_DIR), reverse=True):
            if f.startswith('weather_') and f.endswith('.db'):
                p = os.path.join(BACKUP_DIR, f)
                items.append({
                    'name': f,
                    'size_mb': round(os.path.getsize(p) / 1024 / 1024, 2),
                    'mtime': time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(p))),
                })
    return render_template('backups.html', **_common_ctx('backups'), items=items)


@app.route('/admin/data/insert', methods=['POST'])
def admin_insert_record():
    if not _web_is_admin():
        return redirect('/admin', code=303)
    try:
        t = float(request.form.get('t'))
        h = float(request.form.get('h'))
        p = float(request.form.get('p'))
        if bad_value(t, TEMP_RANGE) or bad_value(h, HUM_RANGE) or bad_value(p, PRES_RANGE):
            raise ValueError('вне диапазона')
        with sqlite3.connect(DB_NAME) as conn:
            conn.execute("INSERT INTO weather_data (temp, hum, pres) VALUES (?, ?, ?)", (t, h, p))
            conn.commit()
        logger.info("Ручной ввод через веб-админку: %s/%s/%s", t, h, p)
    except (TypeError, ValueError) as e:
        logger.warning("Ручной ввод отклонён: %s", e)
    return redirect('/admin/data', code=303)


@app.route('/admin/data/delete', methods=['POST'])
def admin_delete_record():
    if not _web_is_admin():
        return redirect('/admin', code=303)
    try:
        rid = int(request.form.get('id', 0))
    except ValueError:
        rid = 0
    if rid:
        with sqlite3.connect(DB_NAME) as conn:
            conn.execute("DELETE FROM weather_data WHERE id = ?", (rid,))
            conn.commit()
        logger.info("Запись %s удалена через веб-админку", rid)
    return redirect('/admin/data', code=303)


@app.route('/admin/backup/create', methods=['POST'])
def admin_backup_create():
    if not _web_is_admin():
        return redirect('/admin', code=303)
    name = backup_db_sync()
    logger.info("Бэкап из веб-админки: %s", name or 'ошибка')
    return redirect('/admin/backups', code=303)


@app.route('/admin/backups/download/<name>')
def admin_backup_download(name):
    if not _web_is_admin():
        return redirect('/admin', code=303)
    safe = os.path.basename(name)
    if not (safe.startswith('weather_') and safe.endswith('.db')):
        return Response("Not found", status=404)
    path = os.path.join(BACKUP_DIR, safe)
    if not os.path.isfile(path):
        return Response("Not found", status=404)
    return send_file(path, as_attachment=True, download_name=safe)


@app.route('/admin/testmode', methods=['POST'])
def admin_toggle_testmode():
    if not _web_is_admin():
        return redirect('/admin', code=303)
    global TEST_MODE
    TEST_MODE = not TEST_MODE
    logger.info("Тест-режим переключён из веб-админки: %s", TEST_MODE)
    return redirect(request.referrer or '/admin', code=303)


@app.route('/admin/logout', methods=['POST'])
def admin_logout():
    WEB_SESSIONS.pop(request.cookies.get(ADMIN_COOKIE, ""), None)
    resp = redirect('/admin', code=303)
    resp.delete_cookie(ADMIN_COOKIE)
    return resp


@app.route('/admin/users/block', methods=['POST'])
def admin_block():
    if not _web_is_admin():
        return redirect('/admin', code=303)
    try:
        uid = int(request.form.get('user_id', 0))
    except ValueError:
        uid = 0
    if uid:
        with sqlite3.connect(DB_NAME) as conn:
            conn.execute("UPDATE users SET blocked = 1 WHERE user_id = ?", (uid,))
            conn.commit()
        invalidate_blocked_cache()
        logger.info("Пользователь %s заблокирован через веб-админку", uid)
    return redirect('/admin/users', code=303)


@app.route('/admin/users/unblock', methods=['POST'])
def admin_unblock():
    if not _web_is_admin():
        return redirect('/admin', code=303)
    try:
        uid = int(request.form.get('user_id', 0))
    except ValueError:
        uid = 0
    if uid:
        with sqlite3.connect(DB_NAME) as conn:
            conn.execute("UPDATE users SET blocked = 0 WHERE user_id = ?", (uid,))
            conn.commit()
        invalidate_blocked_cache()
        logger.info("Пользователь %s разблокирован через веб-админку", uid)
    return redirect('/admin/users', code=303)


@app.route('/admin/broadcast', methods=['POST'])
def admin_broadcast_web():
    if not _web_is_admin():
        return redirect('/admin', code=303)
    text = (request.form.get('text', '') or '').strip()
    if text:
        web_broadcast_queue.append(text[:1000])
    return redirect('/admin/users', code=303)


@app.route('/admin/chart/<mode>')
def admin_chart(mode):
    if not _web_is_admin():
        return redirect('/admin', code=303)
    demo = request.args.get('demo') == '1'
    mark = ' · тест' if demo else ''
    if mode == '24h':
        rows = get_test_chart_data('daily') if demo else _web_query(f"""
            SELECT strftime('%d', datetime(timestamp, '{TIMEZONE_OFFSET}')) as d,
                   strftime('%H:00', datetime(timestamp, '{TIMEZONE_OFFSET}')) as h,
                   AVG(temp), AVG(hum), MIN(timestamp) as ts
            FROM weather_data WHERE timestamp > datetime('now', '-24 hours')
            GROUP BY d, h ORDER BY ts ASC""")
        buf = _create_chart_sync(rows, 'daily', "Температура за 24ч (— влажность)" + mark)
    elif mode == '7d':
        rows = get_test_chart_data('weekly') if demo else _web_query(f"""
            SELECT strftime('%d.%m', datetime(timestamp, '{TIMEZONE_OFFSET}')) as d, AVG(temp)
            FROM weather_data WHERE timestamp > datetime('now', '-7 days')
            GROUP BY d ORDER BY MIN(timestamp) ASC""")
        buf = _create_chart_sync(rows, 'weekly', "Динамика недели" + mark)
    elif mode == '30d':
        rows = get_test_chart_data('monthly') if demo else _web_query(f"""
            SELECT strftime('%d.%m', datetime(timestamp, '{TIMEZONE_OFFSET}')) as d, AVG(temp)
            FROM weather_data WHERE timestamp > datetime('now', '-30 days')
            GROUP BY d ORDER BY MIN(timestamp) ASC""")
        buf = _create_chart_sync(rows, 'monthly', "Динамика месяца" + mark)
    elif mode == 'dew':
        if demo:
            rows = get_test_chart_data('dew')
        else:
            raw = _web_query(f"""
                SELECT strftime('%d.%m', datetime(timestamp, '{TIMEZONE_OFFSET}')) as d,
                       AVG(temp), AVG(hum)
                FROM weather_data
                WHERE timestamp > datetime('now', '-7 days') AND temp IS NOT NULL AND hum IS NOT NULL
                GROUP BY d ORDER BY MIN(timestamp) ASC""")
            rows = [(r[0], dew_point(r[1], r[2])) for r in (raw or [])]
            rows = [r for r in rows if r[1] is not None]
        buf = _create_chart_sync(rows, 'dew', "Точка росы (неделя)" + mark)
    else:
        return Response("Not found", status=404)
    if buf is None:
        buf = _create_empty_chart_sync({
            '24h': "Температура за 24ч",
            '7d': "Динамика недели",
            '30d': "Динамика месяца",
            'dew': "Точка росы (неделя)",
        }[mode] + mark)
    return Response(buf.read(), mimetype='image/png')


@app.route('/admin/export/csv')
def admin_export_csv():
    if not _web_is_admin():
        return redirect('/admin', code=303)
    rows = _web_query(f"""SELECT id, datetime(timestamp, '{TIMEZONE_OFFSET}'), temp, hum, pres
                          FROM weather_data WHERE timestamp > datetime('now', '-7 days')
                          ORDER BY id ASC""")
    out = io.StringIO()
    out.write("id;дата-время (UTC+3);темп °C;влажность %;давление\n")
    for r in rows:
        out.write(f"{r[0]};{r[1]};{r[2]};{r[3]};{fmt_num(r[4])}\n")
    return Response(out.getvalue().encode("utf-8-sig"), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename="weather_7d.csv"'})


@app.route('/admin/export/xlsx')
def admin_export_xlsx():
    if not _web_is_admin():
        return redirect('/admin', code=303)
    rows = _web_query(f"""SELECT id, datetime(timestamp, '{TIMEZONE_OFFSET}'), temp, hum, pres
                          FROM weather_data WHERE timestamp > datetime('now', '-7 days')
                          ORDER BY id ASC""")
    data = [(r[0], r[1], r[2], r[3], fmt_num(r[4])) for r in rows]
    buf = make_xlsx_bytes(["id", "дата-время (UTC+3)", "Температура °C", "Влажность %", "Давление"], data)
    return Response(buf.read(), mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition': 'attachment; filename="weather_7d.xlsx"'})

# --- ЗАПУСК ---
async def main() -> None:
    logger.info("🚀 Запуск TestV3... База: %s", DB_NAME)
    init_db_sync()

    Thread(target=lambda: app.run(host='0.0.0.0', port=5002, use_reloader=False), daemon=True).start()

    def handle_signal(signum, frame):
        logger.info(f"Получен сигнал {signum}. Завершение работы...")
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    # Фоновые процессы
    asyncio.create_task(silence_watcher())
    asyncio.create_task(sensor_error_watcher())
    asyncio.create_task(temp_jump_watcher())
    asyncio.create_task(frost_watcher())
    asyncio.create_task(esp_alert_watcher())
    asyncio.create_task(daily_digest_loop())
    asyncio.create_task(backup_loop())

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен вручную.")
    except Exception as e:
        logger.exception(f"Критическая ошибка: {e}")
