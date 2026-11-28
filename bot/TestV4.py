#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# TestV4 — Telegram-бот метеостанции «Солигорск»
# Полная версия в одном файле: TestV3 + новые фичи + улучшенные графики.
#
# Новое в TestV4:
#   ГРАФИКИ:
#   1. Сглаживание скользящим средним + «сырая» линия полупрозрачной подложкой.
#   2. Градиентная заливка под кривой (вместо плоской fill_between).
#   3. Ночные часы затемнены на 24ч-графике (по реальному восходу/закату).
#   4. Маркеры минимумов/максимумов.
#   5. Неделя: давление тонкой линией на правой оси.
#   6. Кэш PNG (~50 сек): автообновление админки не грузит Pi.
#   7. Новый график «Давление за 24ч» (кнопка в «Погода за период»).
#   ФИЧИ:
#   8. Жаркий алерт (T >= HEAT_THRESHOLD_C, коулдаун 6 ч).
#   9. Алерт «риск тумана/конденсата» (T − Tdew < 1 °C, влажность >= 90%).
#   10. «🔮 Прогноз» — локальная оценка по тренду давления и точке росы (офлайн).
#   11. «🧥 Как одеться» — рекомендация по ощущаемой температуре (Australian AT).
#   12. «🏆 Рекорды» — абсолютные min/max T/H/P за всю историю с датами.
#   13. «Погода сейчас»: «ощущается как» + сравнение со вчера в это же время.
#   14. Недельный дайджест «Итоги недели» (воскресенье, 19:00 местн.).
#   15. Веб-админка под шаблоны base/login/dashboard/users/data/backups:
#       сессии по cookie, все маршруты, chart с ?demo=1, экспорт CSV/XLSX.
#
# Правки приёмки 2026-11-23 (агент, до развёртывания):
#   A. active_1h: незакрытая Python-строка + битый SQL ('-1 hour) без кавычки)
#      + не учтён TIMEZONE_OFFSET — переписано как в TestV3.
#   B. admin_data: инверсия метки брака (было timestamp <= BAD_DATA_FROM —
#      браком клейметись хорошие февральские данные) → >=, как в TestV3.
#   C. Опечатка в тексте подтверждения очистки БД.

import asyncio
import aiosqlite
import sqlite3
import datetime
import io
import json
import math
import time
import os
import sys
import random
import socket
import psutil
import logging
import logging.handlers
import zipfile
from typing import Optional, List, Tuple
from threading import Thread, Lock
from collections import deque
from flask import Flask, request, redirect, Response, render_template, send_from_directory

# Без монитора — Agg-бэкенд matplotlib
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
import numpy as np  # идёт в комплекте с matplotlib

# pyplot держит глобальное состояние и не потокобезопасен: Flask отдаёт
# картинки параллельно с ботом — рендер сериализуется этим замком.
_PLT_LOCK = Lock()

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramAPIError

# ==================== КОНФИГУРАЦИЯ ====================
# Секреты (токен бота, пароль админа, ключ станции, точные координаты)
# берутся из bot/secrets_local.py (под .gitignore; в репо — secrets_local.example.py).
try:
    import secrets_local as _sec
except ImportError:
    _sec = None   # создай bot/secrets_local.py из secrets_local.example.py

TOKEN = getattr(_sec, "BOT_TOKEN", "")
ADMIN_PASS = getattr(_sec, "ADMIN_PASS", "")
SENSOR_KEY = getattr(_sec, "SENSOR_KEY", "")
HOME_LAT = getattr(_sec, "HOME_LAT", 0.0)
HOME_LON = getattr(_sec, "HOME_LON", 0.0)

# ВАЖНО: проверь путь к диску (df -h). Если диск в /media/pi/..., поменяй путь.
DISK_PATH = "/mnt/weather_data"
DB_NAME = os.path.join(DISK_PATH, "weather.db")
BACKUP_DIR = os.path.join(DISK_PATH, "backups")
LOG_DIR = "logs"

TIMEZONE_OFFSET = "+3 hours"       # Солигорск (UTC+3)
LOCAL_TZ_SHIFT = datetime.timedelta(hours=3)
CITY_LAT = HOME_LAT if HOME_LAT else 52.04   # без точных координат — округлённый центр города (~1 км)
CITY_LON = HOME_LON if HOME_LON else 27.54

DIGEST_HOUR = 21                    # дневной дайджест (местн. час)
WEEKLY_DIGEST_WEEKDAY = 6           # итоги недели: воскресенье
WEEKLY_DIGEST_HOUR = 19             # воскресенье 19:00
SILENCE_LIMIT_MIN = 15              # станция молчит N минут -> алерт
CHECK_INTERVAL_S = 300              # фоновые проверки (5 мин)
TREND_CHECK_INTERVAL_S = 600        # проверка скачка T (10 мин)
JUMP_LIMIT_C = 5.0
JUMP_COOLDOWN_S = 3 * 3600
FROST_THRESHOLD_C = -20.0
FROST_COOLDOWN_S = 6 * 3600
HEAT_THRESHOLD_C = 28.0             # NEW: жаркий алерт
HEAT_COOLDOWN_S = 6 * 3600
FOG_DEW_GAP_C = 1.0                 # NEW: T − Tdew меньше этого = риск тумана
FOG_MIN_HUM = 90
FOG_COOLDOWN_S = 6 * 3600
ALERT_COOLDOWN_S = 3600
BACKUP_KEEP = 7
BACKUP_INTERVAL_S = 24 * 3600
ESP_ALERT_MAX_LEN = 400
CHART_CACHE_TTL_S = 50              # NEW: кэш готовых PNG
WEB_PORT = 8080
WEB_ADMIN_PATH = "/admin"


def lan_ip() -> str:
    """Адрес машины в локальной сети — чтобы ссылку на админку открыть с телефона.

    UDP-сокету connect не нужен живой сервер: он только выбирает маршрут,
    поэтому наружу ничего не уходит.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()

# Сверка с официальной погодой (Open-Meteo, без ключа): тянем почасовую
# температуру за 7 дней, пишем в ref_checks, рисуем график и дельту в админке
# Часовые данные за 7 дней (сверка) и прогноз на 2 суток (график «Прогноз 24ч»);
# прогнозные часы пишутся в ref_checks так же, как фактические (UPSERT по ts)
OPEN_METEO_URL = (f"https://api.open-meteo.com/v1/forecast?latitude={CITY_LAT}&longitude={CITY_LON}"
                  "&hourly=temperature_2m&past_days=7&forecast_days=2&timezone=UTC")
REF_FETCH_INTERVAL_S = 3600
# Показ температуры в боте — среднее станции и официальной: западная стена
# в 10 см греет датчик в ясные послеполуденные часы (+1..3 °C). Сырые данные
# в БД не трогаем — усреднение только на показе. 0 = только станция.
BLEND_WEIGHT_OFFICIAL = 0.5
OPEN_METEO_CURRENT_TTL_S = 600      # кэш «текущей официальной погоды» для админки

# WMO weather codes -> короткое описание
WMO_TEXT = {
    0: "ясно", 1: "малооблачно", 2: "переменная облачность", 3: "пасмурно",
    45: "туман", 48: "изморозь",
    51: "лёгкая морось", 53: "морось", 55: "сильная морось",
    56: "ледяная морось", 57: "сильная ледяная морось",
    61: "небольшой дождь", 63: "дождь", 65: "сильный дождь",
    66: "ледяной дождь", 67: "сильный ледяной дождь",
    71: "небольшой снег", 73: "снег", 75: "сильный снег", 77: "снежные зёрна",
    80: "ливень", 81: "ливень", 82: "сильный ливень",
    85: "снегопад", 86: "сильный снегопад",
    95: "гроза", 96: "гроза с градом", 99: "сильная гроза с градом",
}
WIND_DIRS = ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"]

TEMP_RANGE = (-60.0, 55.0)
HUM_RANGE = (0.0, 100.0)
PRES_RANGE = (300.0, 1100.0)

BAD_DATA_FROM = "2026-02-15 16:20:49"  # граница брака (UTC в БД)

TEST_MODE: bool = False
MAINTENANCE: bool = False

# ==================== ЛОГИРОВАНИЕ ====================
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
logger = logging.getLogger("testv4")

# ==================== ИНИЦИАЛИЗАЦИЯ ====================
bot = Bot(token=TOKEN)
dp = Dispatcher()

_blocked_uids_cache = None
_blocked_uids_ts = 0.0
BLOCKED_CACHE_TTL_S = 60
_admin_uids: set = set()   # кто вошёл в бота по ADMIN_PASS — им доступны тумблеры


async def get_blocked_uids() -> set:
    global _blocked_uids_cache, _blocked_uids_ts
    now = time.time()
    if _blocked_uids_cache is None or now - _blocked_uids_ts > BLOCKED_CACHE_TTL_S:
        rows = await execute_query(
            "SELECT user_id FROM users WHERE IFNULL(blocked, 0) = 1", fetch=True)
        _blocked_uids_cache = {int(r[0]) for r in (rows or [])}
        _blocked_uids_ts = now
    return _blocked_uids_cache


def invalidate_blocked_cache() -> None:
    global _blocked_uids_cache, _blocked_uids_ts
    _blocked_uids_cache = None
    _blocked_uids_ts = 0.0


@dp.message.outer_middleware()
async def gate_middleware(handler, event: types.Message, data: dict):
    uid = getattr(event.from_user, "id", None)
    if uid and uid in await get_blocked_uids():
        logger.info("🚫 Сообщение от заблокированного %s — молча игнорируется", uid)
        return
    # Технический перерыв: всем заглушка, кроме входа в админку и «Возобновить»
    if MAINTENANCE and event.text not in (ADMIN_PASS, "✅ Возобновить"):
        try:
            await event.answer("🛠 Технический перерыв. Бот скоро вернётся!")
        except Exception:
            pass
        return
    return await handler(event, data)


_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Админка — новый дизайн (web54, см. AGENTS.md): шаблоны и статика из папки
# web54 в корне репо. Файл web54/install_admin_ui.py пересоздаёт их при необходимости.
_PROJECT_ROOT = os.path.dirname(_BASE_DIR)
app = Flask(__name__,
            template_folder=os.path.join(_PROJECT_ROOT, 'web54', 'templates'),
            static_folder=os.path.join(_PROJECT_ROOT, 'web54', 'static'))
BOT_START_TIME = time.time()
BOT_STARTED_AT_STR = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

reject_stamps: deque = deque(maxlen=500)
_last_alert_at: dict = {}
silence_flag: bool = False

# Телеметрия станции (прошивка v2 шлёт в каждом /update)
_esp_tel: dict = {'ts': 0.0, 'rssi': None, 'heap': None, 'up_s': None, 'fw': None}

WEB_SESSIONS: dict = {}
ADMIN_COOKIE = "ws_session"
WEB_SESSION_TTL_S = 12 * 3600
web_broadcast_queue: deque = deque(maxlen=20)
esp_alert_queue: deque = deque(maxlen=20)


class DevStates(StatesGroup):
    waiting_for_manual_data = State()
    waiting_for_clear_confirm = State()


# ==================== КЛАВИАТУРЫ ====================
main_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="Погода сейчас"), KeyboardButton(text="Сводка за сегодня")],
    [KeyboardButton(text="Погода за период"), KeyboardButton(text="Пределы 24ч")],
    [KeyboardButton(text="💧 Точка росы"), KeyboardButton(text="📊 Статистика")],
    [KeyboardButton(text="🔮 Прогноз"), KeyboardButton(text="🧥 Как одеться")],
], resize_keyboard=True)

period_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="За 24 часа"), KeyboardButton(text="За неделю")],
    [KeyboardButton(text="За месяц"), KeyboardButton(text="Точка росы (неделя)")],
    [KeyboardButton(text="Давление 24ч"), KeyboardButton(text="Назад")]
], resize_keyboard=True)

limits_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="Макс °C"), KeyboardButton(text="Мин °C")],
    [KeyboardButton(text="Макс %"), KeyboardButton(text="Мин %")],
    [KeyboardButton(text="Макс давл"), KeyboardButton(text="Мин давл")],
    [KeyboardButton(text="🏆 Рекорды"), KeyboardButton(text="Назад")]
], resize_keyboard=True)


def get_admin_kb() -> ReplyKeyboardMarkup:
    test_btn_text = "🧪 Тест без БД: ВКЛ" if TEST_MODE else "🧪 Тест без БД: ВЫКЛ"
    source_btn = ("📡 Источник: Open-Meteo" if get_data_source() == 'om'
                  else "📡 Источник: станция")
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Статус системы"), KeyboardButton(text="📈 Аналитика")],
        [KeyboardButton(text="🌡 CPU и RAM"), KeyboardButton(text="🕒 Последние данные")],
        [KeyboardButton(text="📦 Экспорт CSV"), KeyboardButton(text="📊 Экспорт Excel")],
        [KeyboardButton(text="💾 Бэкап сейчас"), KeyboardButton(text="✍️ Внести данные")],
        [KeyboardButton(text="🧹 Очистить БД"), KeyboardButton(text="🛠 Тех. перерыв")],
        [KeyboardButton(text="✅ Возобновить"), KeyboardButton(text=test_btn_text)],
        [KeyboardButton(text=source_btn), KeyboardButton(text="🔔 Алерты")],
        [KeyboardButton(text="🪪 Мой ID"), KeyboardButton(text="ℹ️ Фичи")],
        [KeyboardButton(text="🖥 Веб-админка"), KeyboardButton(text="🚪 Выход")]
    ], resize_keyboard=True)


# Тумблеры алертов: kind -> подпись кнопки
ALERT_KINDS = {
    'silence': '🔇 Тишина станции',
    'sensor_error': '⚠️ Ошибки датчика',
    'tjump': '⬆️ Скачок T',
    'frost': '🥶 Мороз',
    'heat': '🔥 Жара',
    'fog': '🌫 Туман',
    'digest': '📝 Дайджест 21:00',
    'weekly': '📆 Итоги недели',
}


def get_alerts_kb() -> ReplyKeyboardMarkup:
    rows = []
    for kind, label in ALERT_KINDS.items():
        state = '✅' if alert_enabled(kind) else '❌'
        rows.append([KeyboardButton(text=f"{state} {label}")])
    rows.append([KeyboardButton(text="↩️ Назад к админке")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


ALERT_BTN_TEXTS = {f"{mark} {label}" for mark in ("✅", "❌")
                   for label in ALERT_KINDS.values()}


# ==================== ТЕСТОВЫЕ ДАННЫЕ ====================
def get_test_current_weather() -> Tuple[float, float, float]:
    return (round(random.uniform(-5, 25), 1), random.randint(40, 90), random.randint(730, 770))


def get_test_summary() -> str:
    periods = [("🌙", "Ночь"), ("🌅", "Утро"), ("☀️", "День"), ("🌆", "Вечер")]
    lines = ["📅 **Сводка за сегодня:**"]
    for icon, period in periods:
        lines.append(f"{icon} {period}: {round(random.uniform(0, 10), 1)}°C ... {round(random.uniform(10, 20), 1)}°C")
    return "\n".join(lines)


def get_test_chart_data(mode: str) -> List[Tuple]:
    """Синтетические ряды для проверки графиков. Сид фиксированный."""
    rnd = random.Random(20261118)
    now = datetime.datetime.now()

    if mode == 'ref':
        rows = []
        for i in range(7):
            day = now - datetime.timedelta(days=6 - i)
            ref_t = round(1.0 + 4.0 * math.sin(2 * math.pi * i * 1.3 / 6)
                          + rnd.uniform(-0.5, 0.5), 1)
            ours = round(ref_t + rnd.uniform(-0.6, 0.6), 1)
            rows.append((day.strftime('%d.%m'), ours, ref_t))
        return rows

    if mode == 'forecast':
        rows = []
        for i in range(24):
            ts = now + datetime.timedelta(hours=1 + i)
            hour = ts.hour
            temp = round(2.0 + 6.0 * math.sin(2 * math.pi * (hour - 9) / 24)
                         + rnd.uniform(-0.35, 0.35), 1)
            hum = max(40, min(96, round(84 - 1.8 * (temp - 2.0) + rnd.uniform(-2.5, 2.5))))
            rows.append((ts.strftime('%d'), f"{hour:02d}:00", temp, hum, i))
        return rows

    if mode in ('daily', 'pres24'):
        rows = []
        for i in range(24):
            ts = now - datetime.timedelta(hours=23 - i)
            hour = ts.hour
            temp = round(2.0 + 6.0 * math.sin(2 * math.pi * (hour - 9) / 24)
                         + rnd.uniform(-0.35, 0.35), 1)
            hum = max(40, min(96, round(84 - 1.8 * (temp - 2.0) + rnd.uniform(-2.5, 2.5))))
            pres = round(746 + 3.5 * math.sin(2 * math.pi * (hour - 6) / 24)
                         + rnd.uniform(-0.6, 0.6), 1)
            if mode == 'pres24':
                rows.append((ts.strftime('%d'), f"{hour:02d}:00", pres, i))
            else:
                rows.append((ts.strftime('%d'), f"{hour:02d}:00", temp, hum, i))
        return rows

    days = 7 if mode in ('weekly', 'dew') else 30
    rows = []
    for i in range(days):
        day = now - datetime.timedelta(days=days - 1 - i)
        label = day.strftime('%d.%m')
        temp = round(1.5 + 4.5 * math.sin(2 * math.pi * i * 1.4 / max(days - 1, 1))
                     + rnd.uniform(-1.2, 1.2), 1)
        if mode == 'dew':
            hum = max(55, min(95, round(82 + 6 * math.sin(2 * math.pi * i / 5)
                                        + rnd.uniform(-3, 3))))
            rows.append((label, dew_point(temp, hum)))
        elif mode == 'weekly':
            pres = round(745 + 4 * math.sin(i / 2.6) + rnd.uniform(-0.8, 0.8), 1)
            rows.append((label, temp, pres))
        else:
            rows.append((label, temp))
    return rows


def get_test_limit(metric: str) -> Tuple[float, str]:
    sample = {
        'temp_max': random.uniform(10, 25), 'temp_min': random.uniform(-5, 10),
        'hum_max': random.uniform(70, 95), 'hum_min': random.uniform(30, 60),
        'pres_max': random.uniform(750, 770), 'pres_min': random.uniform(730, 750),
    }[metric]
    return (round(sample, 1), datetime.datetime.now().strftime('%H:%M'))

# ==================== БАЗА ДАННЫХ ====================
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
        conn.execute('''CREATE TABLE IF NOT EXISTS settings
                     (key TEXT PRIMARY KEY, value TEXT)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS user_events
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER, ts DATETIME)''')
        conn.execute('''CREATE INDEX IF NOT EXISTS idx_ue_uid_ts
                        ON user_events(user_id, ts)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS ref_checks
                     (ts TEXT PRIMARY KEY,
                      ref REAL,
                      hum REAL,
                      pres REAL,
                      fetched_at TEXT)''')
        ensure_ref_columns(conn)

        def ensure_column(table: str, column: str, decl: str) -> None:
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
            if column not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

        ensure_column("users", "last_active", "DATETIME")
        ensure_column("users", "blocked", "INTEGER DEFAULT 0")
        ensure_column("users", "first_name", "TEXT")
        ensure_column("users", "username", "TEXT")
        conn.execute("UPDATE users SET last_active = CURRENT_TIMESTAMP "
                     "WHERE last_active IS NULL OR last_active = ''")
        conn.commit()


def ensure_ref_columns(conn) -> None:
    """ref_checks мог быть создан старой версией без hum/pres — добавляем."""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(ref_checks)")]
    for col in ("hum", "pres"):
        if col not in cols:
            conn.execute(f"ALTER TABLE ref_checks ADD COLUMN {col} REAL")


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


def _db_query_sync(query: str, params: Tuple = (), fetch: bool = False, fetch_one: bool = False):
    """Синхронный доступ для Flask-потока (у него нет event loop)."""
    conn = sqlite3.connect(DB_NAME, timeout=10)
    try:
        conn.execute("PRAGMA busy_timeout=10000;")
        cur = conn.execute(query, params)
        if fetch:
            return cur.fetchall()
        if fetch_one:
            return cur.fetchone()
        conn.commit()
        return None
    except Exception as e:
        logger.error(f"🔥 Ошибка БД (sync): {e}")
        return None
    finally:
        conn.close()


async def register_user(user_id: int, first_name: Optional[str] = None,
                        username: Optional[str] = None) -> None:
    await execute_query("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    await execute_query(
        f"UPDATE users SET last_active = datetime('now', '{TIMEZONE_OFFSET}'), "
        f"first_name = COALESCE(?, first_name), username = COALESCE(?, username) "
        f"WHERE user_id = ?",
        (first_name, username, user_id)
    )
    # Событие активности — для визуализации (/admin/activity)
    await execute_query(
        f"INSERT INTO user_events (user_id, ts) VALUES (?, datetime('now', '{TIMEZONE_OFFSET}'))",
        (user_id,))


def get_setting(key: str, default: str = "") -> str:
    """Настройка из таблицы settings (переживает рестарт бота)."""
    r = _db_query_sync("SELECT value FROM settings WHERE key = ?", (key,), fetch_one=True)
    return r[0] if r and r[0] is not None else default


def set_setting(key: str, value: str) -> None:
    _db_query_sync("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))

# ==================== АЛЕРТЫ И РАССЫЛКА ====================
def alert_allowed(kind: str, cooldown: int = ALERT_COOLDOWN_S) -> bool:
    now = time.time()
    if now - _last_alert_at.get(kind, 0) >= cooldown:
        _last_alert_at[kind] = now
        return True
    return False


async def broadcast(text: str) -> int:
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


def alert_enabled(kind: str) -> bool:
    """Тумблер алертов: '1'/'0' из settings, по умолчанию включён."""
    return get_setting('alert_' + kind, '1') == '1'


async def send_alert(kind: str, text: str, cooldown: int = ALERT_COOLDOWN_S) -> None:
    if not alert_enabled(kind):
        return
    if alert_allowed(kind, cooldown):
        await broadcast(text)

# ==================== МЕТЕО-МАТЕМАТИКА ====================
def dew_point(t: float, h: float) -> Optional[float]:
    """Точка росы по Магнусу (a=17.62, b=243.12)."""
    if t is None or h is None or h <= 0:
        return None
    a, b = 17.62, 243.12
    gamma = math.log(min(h, 100) / 100.0) + a * t / (b + t)
    return round(b * gamma / (a - gamma), 1)


def apparent_temp(t: float, h: float) -> Optional[float]:
    """Ощущаемая температура (Australian Apparent Temperature, без ветра)."""
    if t is None or h is None:
        return None
    try:
        e = (h / 100.0) * 6.105 * math.exp(17.27 * t / (237.7 + t))
        return round(t + 0.33 * e - 4.00, 1)
    except Exception:
        return None


def sun_times(date_local: datetime.date) -> Tuple[str, str]:
    """Восход/закат (местное HH:MM) по NOAA-приближению."""
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


def _parse_db_ts(ts: str) -> Optional[datetime.datetime]:
    try:
        return datetime.datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
    except (TypeError, ValueError):
        return None


def _fmt_dt_local(ts) -> str:
    dt = _parse_db_ts(ts) if isinstance(ts, str) else None
    return (dt + LOCAL_TZ_SHIFT).strftime('%d.%m.%Y %H:%M') if dt else '—'


def _local_now() -> datetime.datetime:
    return datetime.datetime.utcnow() + LOCAL_TZ_SHIFT

# ==================== FLASK: ПРИЁМ ДАННЫХ ====================
def bad_value(v: float, rng: Tuple[float, float]) -> bool:
    return not (rng[0] <= v <= rng[1])


@app.route('/update')
def update():
    if request.args.get('key') != SENSOR_KEY:
        logger.warning("🚫 Отказ /update: неверный ключ с %s", request.remote_addr)
        reject_stamps.append(time.time())
        return "Forbidden", 403

    # Необязательный честный timestamp замера (прошивка v2.1 с NTP).
    # Нет ts — бот ставит время приёма (как раньше, совместимо с v1).
    ts_utc = None
    raw_ts = request.args.get('ts')
    if raw_ts:
        ts_dt = _parse_db_ts(raw_ts)
        if not ts_dt:
            logger.warning("🚫 Отказ /update: битый ts=%s с %s", raw_ts, request.remote_addr)
            reject_stamps.append(time.time())
            return "Bad ts", 400
        ts_utc = ts_dt.strftime('%Y-%m-%d %H:%M:%S')

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

    # Необязательная телеметрия станции (прошивка v2): RSSI, ОЗУ, аптайм, версия
    try:
        _esp_tel['rssi'] = int(request.args['rssi'])
        _esp_tel['heap'] = int(request.args['heap'])
        _esp_tel['up_s'] = int(request.args['up'])
        _esp_tel['fw'] = str(request.args.get('fw', ''))[:16]
        _esp_tel['ts'] = time.time()
    except (KeyError, ValueError, TypeError):
        pass  # старая прошивка без телеметрии — не ошибка

    try:
        with sqlite3.connect(DB_NAME, timeout=10) as conn:
            conn.execute("PRAGMA busy_timeout=10000;")
            if ts_utc:
                conn.execute(
                    "INSERT INTO weather_data (timestamp, temp, hum, pres) VALUES (?, ?, ?, ?)",
                    (ts_utc, t, h, p))
            else:
                conn.execute("INSERT INTO weather_data (temp, hum, pres) VALUES (?, ?, ?)",
                             (t, h, p))
            conn.commit()
        return "OK", 200
    except Exception as e:
        logger.error(f"Flask /update error: {e}")
        return str(e), 500


@app.route('/update_batch', methods=['POST'])
def update_batch():
    """Пакет замеров store-and-forward (прошивка v2.1): JSON
    {"readings": [{"ts": "YYYY-MM-DD HH:MM:SS", "t": .., "h": .., "p": ..}, ...]}
    ts обязателен и в UTC. Дубликаты ts пропускаются (повторная отправка
    после потери ответа не плодит дубли в базе)."""
    if request.args.get('key') != SENSOR_KEY:
        logger.warning("🚫 Отказ /update_batch: неверный ключ с %s", request.remote_addr)
        reject_stamps.append(time.time())
        return "Forbidden", 403
    try:
        payload = request.get_json(force=True)
        readings = payload.get('readings') if isinstance(payload, dict) else None
    except Exception:
        logger.warning("🚫 Отказ /update_batch: невалидный JSON с %s", request.remote_addr)
        return "Bad json", 400
    if not isinstance(readings, list) or not (0 < len(readings) <= 500):
        return "Bad batch", 400

    inserted, skipped = 0, 0
    conn = sqlite3.connect(DB_NAME, timeout=15)
    try:
        conn.execute("PRAGMA busy_timeout=10000;")
        for r in readings:
            try:
                ts = str(r['ts'])[:19]
                datetime.datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
                t = float(r['t'])
                h = float(r['h'])
                p = float(r['p']) if r.get('p') is not None else None
            except (KeyError, ValueError, TypeError):
                skipped += 1
                continue
            if bad_value(t, TEMP_RANGE) or bad_value(h, HUM_RANGE) \
                    or (p is not None and bad_value(p, PRES_RANGE)):
                skipped += 1
                continue
            if conn.execute("SELECT 1 FROM weather_data WHERE timestamp = ?",
                            (ts,)).fetchone():
                skipped += 1
                continue
            conn.execute(
                "INSERT INTO weather_data (timestamp, temp, hum, pres) VALUES (?, ?, ?, ?)",
                (ts, t, h, p))
            inserted += 1
        conn.commit()
    except Exception as e:
        logger.error(f"Flask /update_batch error: {e}")
        return str(e), 500
    finally:
        conn.close()
    logger.info("update_batch: вставлено %d, пропущено %d", inserted, skipped)
    return json.dumps({"ok": True, "inserted": inserted, "skipped": skipped}), 200


@app.route('/alert')
def esp_alert():
    """Труба алертов из прошивки ESP32: /alert?key=..&text=.."""
    if request.args.get('key') != SENSOR_KEY:
        logger.warning("🚫 Отказ /alert: неверный ключ с %s", request.remote_addr)
        return "Forbidden", 403
    text = (request.args.get('text') or '').strip()
    if not text:
        return "Empty", 400
    if not alert_allowed(f'esp:{text[:80]}'):
        return "OK (throttled)", 200
    esp_alert_queue.append(text[:ESP_ALERT_MAX_LEN])
    return "OK", 200


@app.route('/health')
def health():
    return "OK", 200

# ==================== ФОНОВЫЕ WATCHER'Ы ====================
async def esp_alert_watcher() -> None:
    while True:
        try:
            while esp_alert_queue:
                text = esp_alert_queue.popleft()
                await broadcast(f"📡 От станции: {text}")
            while web_broadcast_queue:
                text = web_broadcast_queue.popleft()
                sent = await broadcast(text)
                logger.info("Рассылка веб-админки отправлена (%d получ.)", sent)
        except Exception:
            logger.exception("Ошибка в esp_alert_watcher")
        await asyncio.sleep(2)


async def silence_watcher() -> None:
    global silence_flag
    while True:
        try:
            row = await execute_query("SELECT MAX(timestamp) FROM weather_data", fetch_one=True)
            if row and row[0]:
                last = _parse_db_ts(row[0])
                if last:
                    mins_ago = (datetime.datetime.utcnow() - last).total_seconds() / 60.0
                    if mins_ago > SILENCE_LIMIT_MIN:
                        if (not silence_flag and alert_allowed('silence')
                                and alert_enabled('silence')):
                            silence_flag = True
                            await broadcast(f"🔇 Станция не отвечает: последний замер "
                                            f"{int(mins_ago)} мин назад (> {SILENCE_LIMIT_MIN} мин).")
                    elif silence_flag:
                        silence_flag = False
                        _last_alert_at.pop('silence', None)
                        if alert_enabled('silence'):
                            await broadcast("🟢 Станция вернулась в онлайн, данные снова пишутся.")
        except Exception:
            logger.exception("Ошибка в silence_watcher")
        await asyncio.sleep(CHECK_INTERVAL_S)


async def sensor_error_watcher() -> None:
    while True:
        try:
            now = time.time()
            recent = [s for s in reject_stamps if now - s <= 15 * 60]
            reject_stamps.clear()
            reject_stamps.extend(recent)
            if len(recent) >= 3 and alert_allowed('sensor_error'):
                await broadcast(f"⚠️ Станция передаёт некорректные данные: {len(recent)} отказов "
                                f"за 15 мин (вне диапазона / неверный ключ).")
        except Exception:
            logger.exception("Ошибка в sensor_error_watcher")
        await asyncio.sleep(CHECK_INTERVAL_S)


async def temp_jump_watcher() -> None:
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
                    await broadcast(f"{arrow} Резкое изменение температуры: {delta:+.1f} °C "
                                    f"за последние ~30 мин (было {round(prev_stats[0], 1)}, "
                                    f"стало {round(now_stats[0], 1)}).")
        except Exception:
            logger.exception("Ошибка в temp_jump_watcher")
        await asyncio.sleep(TREND_CHECK_INTERVAL_S)


async def frost_watcher() -> None:
    while True:
        try:
            row = await execute_query(
                "SELECT temp FROM weather_data ORDER BY id DESC LIMIT 1", fetch_one=True)
            if row and row[0] is not None and row[0] <= FROST_THRESHOLD_C:
                if alert_allowed('frost', FROST_COOLDOWN_S):
                    await broadcast(f"🥶 Мороз!: текущая температура {round(row[0], 1)} °C "
                                    f"(ниже {FROST_THRESHOLD_C} °C).")
        except Exception:
            logger.exception("Ошибка в frost_watcher")
        await asyncio.sleep(CHECK_INTERVAL_S)


async def heat_watcher() -> None:
    """NEW: жаркий алерт — симметрично морозному."""
    while True:
        try:
            row = await execute_query(
                "SELECT temp FROM weather_data ORDER BY id DESC LIMIT 1", fetch_one=True)
            if row and row[0] is not None and row[0] >= HEAT_THRESHOLD_C:
                if alert_allowed('heat', HEAT_COOLDOWN_S):
                    await broadcast(f"🔥 Жара: текущая температура {round(row[0], 1)} °C "
                                    f"(выше {HEAT_THRESHOLD_C} °C). Пей больше воды ☀️")
        except Exception:
            logger.exception("Ошибка в heat_watcher")
        await asyncio.sleep(CHECK_INTERVAL_S)


async def fog_watcher() -> None:
    """NEW: риск тумана/конденсата — T почти сравнялась с точкой росы."""
    while True:
        try:
            row = await execute_query(
                "SELECT temp, hum FROM weather_data ORDER BY id DESC LIMIT 1", fetch_one=True)
            if row and row[0] is not None and row[1] is not None:
                dpv = dew_point(row[0], row[1])
                if (dpv is not None and (row[0] - dpv) < FOG_DEW_GAP_C
                        and row[1] >= FOG_MIN_HUM and alert_allowed('fog', FOG_COOLDOWN_S)):
                    await broadcast(f"🌫 Риск тумана/сырости: температура {round(row[0], 1)}°C "
                                    f"почти равна точке росы {dpv}°C "
                                    f"(влажность {round(row[1])}%).")
        except Exception:
            logger.exception("Ошибка в fog_watcher")
        await asyncio.sleep(CHECK_INTERVAL_S)


async def daily_digest_loop() -> None:
    while True:
        now = _local_now()
        target = now.replace(hour=DIGEST_HOUR, minute=0, second=0, microsecond=0)
        if target <= now:
            target += datetime.timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        try:
            if not alert_enabled('digest'):
                continue
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
                tel_line = ""
                if _esp_tel['ts'] and time.time() - _esp_tel['ts'] < 7200:
                    tel_line = (f"\n📶 Станция: RSSI {_esp_tel.get('rssi')} dBm · "
                                f"ОЗУ {_esp_tel.get('heap')} B · прошивка {_esp_tel.get('fw')}")
                await broadcast(f"📝 **Ежедневный дайджест**\n━━━━━━━━━━━━\n"
                                f"🌡 Температура: {round(stats[1], 1)}…{round(stats[2], 1)} °C\n"
                                f"💧 Влажность: {round(stats[3], 1)}…{round(stats[4], 1)} %\n"
                                f"📥 Записей за сутки: {stats[0]}\n"
                                f"⏱ Uptime бота: {uptime}"
                                f"{tel_line}")
        except Exception:
            logger.exception("Ошибка в daily_digest_loop")


async def weekly_digest_loop() -> None:
    """NEW: итоги недели — воскресенье, WEEKLY_DIGEST_HOUR по местному."""
    while True:
        now = _local_now()
        target = now.replace(hour=WEEKLY_DIGEST_HOUR, minute=0, second=0, microsecond=0)
        target += datetime.timedelta(days=(WEEKLY_DIGEST_WEEKDAY - now.weekday()) % 7)
        if target <= now:
            target += datetime.timedelta(days=7)
        await asyncio.sleep((target - now).total_seconds())
        if not alert_enabled('weekly'):
            continue
        try:
            s = await execute_query(
                """SELECT COUNT(*), MIN(temp), MAX(temp), ROUND(AVG(temp), 1),
                          MIN(hum), MAX(hum), MIN(pres), MAX(pres)
                   FROM weather_data WHERE timestamp > datetime('now', '-7 days')""",
                fetch_one=True)
            if not s or not s[0] or s[1] is None:
                await broadcast("📆 **Итоги недели**: данных за неделю не было.")
                continue
            await broadcast("📆 **Итоги недели**\n━━━━━━━━━━━━\n"
                            f"🌡 Температура: {fmt_num(s[1])}…{fmt_num(s[2])} °C (ср {fmt_num(s[3])})\n"
                            f"💧 Влажность: {fmt_num(s[4])}…{fmt_num(s[5])} %\n"
                            f"☁️ Давление: {fmt_num(s[6])}…{fmt_num(s[7])} мм\n"
                            f"📥 Записей: {s[0]}")
        except Exception:
            logger.exception("Ошибка в weekly_digest_loop")


def backup_db_sync() -> Optional[str]:
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M')
        dst_name = os.path.join(BACKUP_DIR, f"weather_{stamp}.db")
        src = sqlite3.connect(DB_NAME)
        dst = sqlite3.connect(dst_name)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        backups = sorted(f for f in os.listdir(BACKUP_DIR)
                         if f.startswith("weather_") and f.endswith(".db"))
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
        # Чистка старых событий активности (визуализация /admin/activity)
        try:
            await execute_query(
                "DELETE FROM user_events WHERE ts < datetime('now', '-30 days')")
        except Exception:
            logger.exception("Ошибка чистки user_events")


def _fetch_ref_sync() -> Optional[list]:
    """Почасовой официальный эталон за 7 дней:
    (ts UTC 'YYYY-MM-DD HH:MM:SS', temp °C, hum %, pres мм рт. ст.)."""
    import urllib.request
    url = OPEN_METEO_URL.replace(
        'hourly=temperature_2m',
        'hourly=temperature_2m,relative_humidity_2m,surface_pressure')
    req = urllib.request.Request(url, headers={'User-Agent': 'soligorsk-meteo/1.0'})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    hourly = data.get('hourly') or {}
    times = hourly.get('time') or []
    temps = hourly.get('temperature_2m') or []
    hums = hourly.get('relative_humidity_2m') or []
    press = hourly.get('surface_pressure') or []
    out = []
    for ts, tv, hv, pv in zip(times, temps, hums, press):
        if tv is None:
            continue
        iso = ts.replace('T', ' ')
        if len(iso) == 16:
            iso += ':00'
        hum_v = round(float(hv), 1) if hv is not None else None
        pres_v = round(float(pv) * 760.0 / 1013.25, 1) if pv is not None else None
        out.append((iso, round(float(tv), 2), hum_v, pres_v))
    return out or None


async def ref_watcher() -> None:
    """Раз в час: тянем официальный эталон и пишем в ref_checks (UPSERT за окно)."""
    while True:
        try:
            rows = await asyncio.to_thread(_fetch_ref_sync)
            if rows:
                fetched_at = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                with sqlite3.connect(DB_NAME, timeout=10) as conn:
                    conn.execute("PRAGMA busy_timeout=10000;")
                    conn.executemany(
                        "INSERT OR REPLACE INTO ref_checks "
                        "(ts, ref, hum, pres, fetched_at) VALUES (?, ?, ?, ?, ?)",
                        [(ts, tv, hv, pv, fetched_at) for ts, tv, hv, pv in rows])
                    conn.execute("DELETE FROM ref_checks WHERE ts < datetime('now', '-30 days')")
                    conn.commit()
                logger.info("Open-Meteo: обновлено %d часов", len(rows))
            else:
                logger.warning("Open-Meteo: пустой ответ")
        except Exception:
            logger.warning("Open-Meteo недоступен — работаем на старых данных")
        await asyncio.sleep(REF_FETCH_INTERVAL_S)


# --- Глобальный источник данных: 'station' | 'om' (Open-Meteo) ---
# Тумблеры: кнопка в админке + кнопка в клавиатуре админа бота.

def get_data_source() -> str:
    return 'om' if get_setting('data_source') == 'om' else 'station'


def set_data_source(mode: str) -> None:
    if mode in ('station', 'om'):
        set_setting('data_source', mode)


async def toggle_data_source() -> str:
    new_mode = 'station' if get_data_source() == 'om' else 'om'
    set_data_source(new_mode)
    return new_mode


def _pres_delta_3h_ref_sync() -> Optional[float]:
    """Тренд давления из эталона ref_checks (для om-режима): последнее
    часовое среднее минус среднее 3-4 часа назад."""
    pn = _db_query_sync(
        "SELECT AVG(pres) FROM ref_checks "
        "WHERE ts > datetime('now', '-2 hours') AND ts <= datetime('now') "
        "AND pres IS NOT NULL", fetch_one=True)
    pp = _db_query_sync(
        "SELECT AVG(pres) FROM ref_checks "
        "WHERE ts BETWEEN datetime('now', '-5 hours') AND datetime('now', '-3 hours') "
        "AND pres IS NOT NULL", fetch_one=True)
    if pn and pp and pn[0] is not None and pp[0] is not None:
        return pn[0] - pp[0]
    return None


# ==================== СВОДКА / ТЕКСТЫ ====================
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


async def _pressure_delta_3h() -> Optional[float]:
    """Тренд давления: средние последних 30 мин минус 3–3.5 ч назад."""
    p_now = await execute_query(
        "SELECT AVG(pres) FROM weather_data WHERE timestamp > datetime('now', '-30 minutes') "
        "AND pres IS NOT NULL", fetch_one=True)
    p_before = await execute_query(
        "SELECT AVG(pres) FROM weather_data "
        "WHERE timestamp BETWEEN datetime('now', '-210 minutes') AND datetime('now', '-180 minutes') "
        "AND pres IS NOT NULL", fetch_one=True)
    if p_now and p_before and p_now[0] is not None and p_before[0] is not None:
        return p_now[0] - p_before[0]
    return None


async def get_display_temp() -> Optional[dict]:
    """Температура для показа. В om-режиме — только официальная (Open-Meteo);
    в станционном — усреднение станции и официальной.

    Возвращает {'blended', 'station', 'official', 'mixed', 'source'} или None.
    Официальная кэшируется на OPEN_METEO_CURRENT_TTL_S (общий кэш с админкой).
    """
    row = await execute_query(
        "SELECT temp FROM weather_data WHERE temp IS NOT NULL "
        "ORDER BY id DESC LIMIT 1", fetch_one=True)
    station = row[0] if row and row[0] is not None else None
    om_mode = get_data_source() == 'om'

    official = None
    now_ts = time.time()
    if now_ts - _openmeteo_cur['ts'] > OPEN_METEO_CURRENT_TTL_S or not _openmeteo_cur['data']:
        try:
            cur = await asyncio.to_thread(_openmeteo_current_sync)
            if cur:
                _openmeteo_cur['data'] = cur
                _openmeteo_cur['ts'] = now_ts
        except Exception as e:
            logger.warning(f"Open-Meteo current (для усреднения): {e}")
    d = _openmeteo_cur['data']
    if d and d.get('temp') is not None:
        official = d['temp']

    if TEST_MODE and station is not None:
        official = round(station + random.uniform(-0.4, 0.4), 1)

    if om_mode:
        if official is None and station is not None:
            return {'blended': round(station, 1), 'station': round(station, 1),
                    'official': None, 'mixed': False, 'source': 'station'}
        return {'blended': official, 'station': station, 'official': official,
                'mixed': False, 'source': 'om'}

    if station is None and official is None:
        return None
    if station is None:
        return {'blended': official, 'station': None, 'official': official, 'mixed': False}
    if official is None:
        return {'blended': round(station, 1), 'station': round(station, 1),
                'official': None, 'mixed': False}
    blended = round(station * (1.0 - BLEND_WEIGHT_OFFICIAL)
                    + official * BLEND_WEIGHT_OFFICIAL, 1)
    return {'blended': blended, 'station': round(station, 1),
            'official': official, 'mixed': True}


async def weather_now_text() -> Optional[str]:
    # om-режим: показываем текущие условия Open-Meteo вместо станции
    if get_data_source() == 'om':
        cur = await asyncio.to_thread(_openmeteo_current_sync)
        if not cur:
            return "🌐 Open-Meteo недоступен."
        dp = dew_point(cur.get('temp'), cur.get('hum'))
        dew_str = f"💧 Точка росы: {dp}°C\n" if dp is not None else ""
        wind_str = ""
        if cur.get('wind_ms') is not None:
            wind_str = (f"💨 Ветер: {cur['wind_ms']} м/с, "
                        f"{cur.get('wind_dir', '—')}\n")
        precip_str = ""
        if cur.get('precip') is not None:
            precip_str = f"🌧 Осадки за час: {cur['precip']} мм\n"
        return (f"🌐 Официальная погода (Open-Meteo)\n"
                f"🌡 Температура: {fmt_num(cur.get('temp'))}°C\n"
                f"🌡 Ощущается как: {fmt_num(cur.get('feels'))}°C\n"
                f"💧 Влажность: {fmt_num(cur.get('hum'))}%\n"
                f"☁️ Давление: {fmt_num(cur.get('pressure_mm'))} мм\n"
                f"{wind_str}"
                f"{precip_str}"
                f"📜 {cur.get('weather', '—')}\n"
                f"⏱ Наблюдение: {cur.get('obs_local', '—')} (местн.)")

    res = await execute_query(
        "SELECT temp, hum, pres FROM weather_data ORDER BY id DESC LIMIT 1", fetch_one=True)
    if not res:
        return None

    disp = await get_display_temp()
    # Заголовок — усреднённая; влажность/давление/тренд — со станции.
    # Сравнение со вчера — станция против станции: сдвиг стены самовычитается.
    disp_temp = disp['blended'] if disp else res[0]

    row = await execute_query("SELECT MAX(timestamp) FROM weather_data", fetch_one=True)
    age_str = ""
    if row and row[0]:
        last = _parse_db_ts(row[0])
        if last:
            mins = int((datetime.datetime.utcnow() - last).total_seconds() // 60)
            age_str = f"\n⏱ Замер {human_dh(mins * 60)} назад"

    d = await _pressure_delta_3h()
    trend = ""
    if d is not None:
        if d <= -1.5:
            trend = " ⬇️ (давление падает — к непогоде)"
        elif d >= 1.5:
            trend = " ⬆️ (давление растёт — к ясному)"
        else:
            trend = " ➡️ ровно"

    dp = dew_point(disp_temp, res[1])
    feels = apparent_temp(disp_temp, res[1])
    dew_str = f"💧 Точка росы: {dp}°C\n" if dp is not None else ""
    feels_str = f"🌡 Ощущается как: {feels}°C\n" if feels is not None else ""

    blend_str = ""
    if disp and disp['mixed']:
        blend_str = (f"\n⚖️ Усреднено: станция {disp['station']}°C + "
                     f"офиц. {disp['official']}°C (стена греет датчик днём)")

    # NEW: сравнение со вчера в это же время
    cmp_str = ""
    y = await execute_query(
        "SELECT AVG(temp) FROM weather_data WHERE timestamp BETWEEN "
        "datetime('now', '-1440 minutes') AND datetime('now', '-1410 minutes') "
        "AND temp IS NOT NULL", fetch_one=True)
    if y and y[0] is not None:
        diff = res[0] - y[0]
        word = "теплее" if diff > 0 else "холоднее" if diff < 0 else "так же"
        cmp_str = (f"\n📅 Вчера в это время: {round(y[0], 1)}°C "
                   f"(сегодня на {abs(round(diff, 1))}° {word})")

    return (f"🌡 Температура: {disp_temp}°C\n"
            f"{feels_str}"
            f"💧 Влажность: {res[1]}%\n"
            f"☁️ Давление: {fmt_num(res[2])} мм{trend}\n"
            f"{dew_str}"
            f"{cmp_str}"
            f"{blend_str}"
            f"{age_str}")


async def forecast_text() -> str:
    """NEW: локальный прогноз по своим данным, без внешних моделей."""
    if TEST_MODE:
        return ("🔮 **Прогноз (TEST)**\n➡️ Давление стабильно. "
                "Без осадков, ночью до +2°C.")
    lines = ["🔮 **Локальный прогноз** (по данным станции, без внешних моделей):\n"]
    d = await _pressure_delta_3h()
    if d is None:
        lines.append("☁️ Давление: недостаточно данных для тренда")
    elif d <= -3:
        lines.append(f"⬇️ Давление резко падает ({d:+.1f} мм/3ч) — вероятны осадки "
                     f"и ветер в ближайшие 12 ч.")
    elif d <= -1.5:
        lines.append(f"⬇️ Давление падает ({d:+.1f} мм/3ч) — возможна пасмурность, осадки.")
    elif d >= 3:
        lines.append(f"⬆️ Давление резко растёт ({d:+.1f} мм/3ч) — прояснение, "
                     f"возможно похолодание.")
    elif d >= 1.5:
        lines.append(f"⬆️ Давление растёт ({d:+.1f} мм/3ч) — к ясной погоде.")
    else:
        lines.append("➡️ Давление стабильно — резких перемен не ожидается.")

    row = await execute_query(
        "SELECT temp, hum FROM weather_data ORDER BY id DESC LIMIT 1", fetch_one=True)
    if row and row[0] is not None and row[1] is not None:
        dpv = dew_point(row[0], row[1])
        if dpv is not None and (row[0] - dpv) < 1.5:
            lines.append("🌫 T близка к точке росы — вероятны туман/роса, особенно утром.")
        if dpv is not None and dpv >= 16:
            lines.append("💧 Душно: высокая влажность, осадки маловероятны без падения давления.")

    t_now = await execute_query(
        "SELECT AVG(temp) FROM weather_data WHERE timestamp > datetime('now', '-30 minutes') "
        "AND temp IS NOT NULL", fetch_one=True)
    t_yest = await execute_query(
        "SELECT AVG(temp) FROM weather_data WHERE timestamp BETWEEN "
        "datetime('now', '-1470 minutes') AND datetime('now', '-1440 minutes') "
        "AND temp IS NOT NULL", fetch_one=True)
    if t_now and t_yest and t_now[0] is not None and t_yest[0] is not None:
        diff = t_now[0] - t_yest[0]
        if diff >= 1:
            lines.append(f"🌡 За сутки потеплело на {round(diff, 1)}°C.")
        elif diff <= -1:
            lines.append(f"🌡 За сутки похолодало на {abs(round(diff, 1))}°C.")

    sunrise, sunset = sun_times(_local_now().date())
    lines.append(f"🌅 Восход: {sunrise} | 🌇 Закат: {sunset}")
    return "\n".join(lines)


def dress_advice(t: float, h: float) -> str:
    """NEW: рекомендация одежды по ощущаемой температуре."""
    feels = apparent_temp(t, h) or t
    if feels >= 28:
        base = "🩳 Жарко: лёгкая одежда, футболка, пей больше воды"
    elif feels >= 22:
        base = "👕 Тепло: футболка/рубашка, вечером — лёгкая кофта"
    elif feels >= 16:
        base = "🧥 Прохладно: рубашка + лёгкая куртка или худи"
    elif feels >= 10:
        base = "🍂 Осень: куртка, длинные рукава"
    elif feels >= 4:
        base = "🧣 Холодно: тёплая куртка, шапка не помешает"
    elif feels >= -5:
        base = "🧤 Морозно: зимняя куртка, шапка, перчатки"
    elif feels >= -15:
        base = "❄️ Сильный мороз: пуховик, варежки, тёплая обувь"
    else:
        base = "🥶 Экстремальный мороз: максимум слоёв, без нужды не выходи!"
    tips = []
    dpv = dew_point(t, h)
    if dpv is not None and dpv >= 16:
        tips.append("влажно и душно")
    if dpv is not None and (t - dpv) < 1.5:
        tips.append("сыро, возможен туман — осторожнее на дороге")
    if h is not None and h >= 90:
        tips.append("высокая влажность")
    if tips:
        base += "\n💡 " + ", ".join(tips).capitalize()
    return base


async def records_text() -> str:
    """NEW: абсолютные рекорды за всю историю."""
    if TEST_MODE:
        return ("🏆 **Рекорды (TEST):**\n"
                "🌡 T: мин −25.4°C (01.01.2026 06:12), макс 31.2°C (15.07.2025 15:40)\n"
                "💧 Вл.: мин 23.0%, макс 98.0%\n"
                "☁️ Давл.: мин 726.8 мм, макс 771.2 мм")
    lines = ["🏆 **Абсолютные рекорды (вся история):**\n"]
    for metric, name, unit in (("temp", "🌡 T", "°C"), ("hum", "💧 Влажность", "%"),
                               ("pres", "☁️ Давление", " мм")):
        lo = await execute_query(
            f"SELECT {metric}, timestamp FROM weather_data WHERE {metric} IS NOT NULL "
            f"ORDER BY {metric} ASC LIMIT 1", fetch_one=True)
        hi = await execute_query(
            f"SELECT {metric}, timestamp FROM weather_data WHERE {metric} IS NOT NULL "
            f"ORDER BY {metric} DESC LIMIT 1", fetch_one=True)
        if lo and lo[0] is not None:
            lines.append(f"{name}: мин {fmt_num(lo[0])}{unit} ({_fmt_dt_local(lo[1])}), "
                         f"макс {fmt_num(hi[0])}{unit} ({_fmt_dt_local(hi[1])})")
        else:
            lines.append(f"{name}: данных нет")
    return "\n".join(lines)

# ==================== ГРАФИКИ (V4) ====================
CHART_LABELS = {
    'daily': "Температура за 24 часа",
    'pres24': "Давление за 24 часа",
    'weekly': "Динамика недели",
    'monthly': "Динамика месяца",
    'dew': "Точка росы (неделя)",
    'ref': "Сверка с официальной (Open-Meteo)",
    'forecast': "Прогноз 24ч",
}

CHART_SQL = {
    'daily': f"""
        SELECT strftime('%d', datetime(timestamp, '{TIMEZONE_OFFSET}')) as d,
               strftime('%H:00', datetime(timestamp, '{TIMEZONE_OFFSET}')) as h,
               AVG(temp), AVG(hum), MIN(timestamp) as ts
        FROM weather_data WHERE timestamp > datetime('now', '-24 hours')
        GROUP BY d, h ORDER BY ts ASC
    """,
    'pres24': f"""
        SELECT strftime('%d', datetime(timestamp, '{TIMEZONE_OFFSET}')) as d,
               strftime('%H:00', datetime(timestamp, '{TIMEZONE_OFFSET}')) as h,
               AVG(pres), MIN(timestamp) as ts
        FROM weather_data WHERE timestamp > datetime('now', '-24 hours') AND pres IS NOT NULL
        GROUP BY d, h ORDER BY ts ASC
    """,
    'weekly': f"""
        SELECT strftime('%d.%m', datetime(timestamp, '{TIMEZONE_OFFSET}')) as d,
               AVG(temp), AVG(pres)
        FROM weather_data WHERE timestamp > datetime('now', '-7 days')
        GROUP BY d ORDER BY MIN(timestamp) ASC
    """,
    'monthly': f"""
        SELECT strftime('%d.%m', datetime(timestamp, '{TIMEZONE_OFFSET}')) as d, AVG(temp)
        FROM weather_data WHERE timestamp > datetime('now', '-30 days')
        GROUP BY d ORDER BY MIN(timestamp) ASC
    """,
    'dew': f"""
        SELECT strftime('%d.%m', datetime(timestamp, '{TIMEZONE_OFFSET}')) as d,
               AVG(temp), AVG(hum)
        FROM weather_data
        WHERE timestamp > datetime('now', '-7 days') AND temp IS NOT NULL AND hum IS NOT NULL
        GROUP BY d ORDER BY MIN(timestamp) ASC
    """,
}

# Кэш готовых PNG: (mode, demo) -> (время_протухания, bytes)
_chart_cache: dict = {}


def _chart_cache_get(key):
    item = _chart_cache.get(key)
    if item and item[0] > time.time():
        return item[1]
    return None


def _chart_cache_put(key, data: bytes) -> None:
    _chart_cache[key] = (time.time() + CHART_CACHE_TTL_S, data)


def invalidate_chart_cache() -> None:
    _chart_cache.clear()


def _postprocess_rows(mode: str, rows) -> list:
    if not rows:
        return []
    if mode == 'dew':
        out = []
        for r in rows:
            dpv = dew_point(r[1], r[2])
            if dpv is not None:
                out.append((r[0], dpv))
        return out
    val_idx = {'daily': 2, 'forecast': 2, 'pres24': 2, 'weekly': 1, 'monthly': 1}[mode]
    return [tuple(r) for r in rows if r[val_idx] is not None]


def _smooth(vals: List[float], window: int = 3) -> List[float]:
    """Скользящее среднее для плавной кривой."""
    if window <= 1 or len(vals) <= window:
        return list(vals)
    half = window // 2
    out = []
    for i in range(len(vals)):
        lo, hi = max(0, i - half), min(len(vals), i + half + 1)
        seg = vals[lo:hi]
        out.append(sum(seg) / len(seg))
    return out


def _gradient_fill(ax, x, y, color: str, bottom: float) -> None:
    """Градиентная заливка под кривой: RGBA-градиент, обрезанный полигоном."""
    rgb = matplotlib.colors.to_rgb(color)
    grad = np.zeros((256, 1, 4))
    grad[..., 0], grad[..., 1], grad[..., 2] = rgb
    grad[..., 3] = np.linspace(0.02, 0.32, 256)[:, None]  # ярче к линии
    verts = [(x[0], bottom)] + list(zip(x, y)) + [(x[-1], bottom)]
    poly = Polygon(verts, closed=True, facecolor='none', edgecolor='none')
    ax.add_patch(poly)
    im = ax.imshow(grad, extent=[min(x) - 0.5, max(x) + 0.5, bottom, max(y) + 0.5],
                   aspect='auto', origin='lower', zorder=1, interpolation='bilinear')
    im.set_clip_path(poly)


def _render_chart_locked(rows: List[Tuple], mode: str, label: str) -> Optional[bytes]:
    if not rows:
        return None
    plt.style.use('default')
    fig, ax = plt.subplots(figsize=(12, 6), dpi=120)

    BG, TXT, GRID = '#0f1419', '#c0c8d1', '#1e2734'
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)

    now_day = datetime.datetime.now().strftime('%d')
    ax2 = None
    unit = '°C'

    if mode == 'daily':
        labels = [f"{'Сег' if r[0] == now_day else 'Вчр'} {r[1]}" for r in rows]
        data = [round(r[2], 1) for r in rows]
        hum = [r[3] for r in rows]
        line_color = '#0ea5e9'
    elif mode == 'forecast':
        labels = [f"{'Сег' if r[0] == now_day else 'Зав'} {r[1]}" for r in rows]
        data = [round(r[2], 1) for r in rows]
        hum = [r[3] for r in rows]
        line_color = '#8b5cf6'
    elif mode == 'pres24':
        labels = [f"{'Сег' if r[0] == now_day else 'Вчр'} {r[1]}" for r in rows]
        data = [round(r[2], 1) for r in rows]
        hum, line_color, unit = None, '#f59e0b', ' мм'
    elif mode == 'weekly':
        labels = [r[0] for r in rows]
        data = [round(r[1], 1) for r in rows]
        pres = [r[2] for r in rows]
        hum, line_color = None, '#2563eb'
    elif mode == 'monthly':
        labels, data = [r[0] for r in rows], [round(r[1], 1) for r in rows]
        hum, line_color = None, '#2563eb'
    else:  # dew
        labels, data = [r[0] for r in rows], [round(r[1], 1) for r in rows]
        hum, line_color, unit = None, '#a3e635', ''

    x = list(range(len(data)))
    mn, mx = min(data), max(data)
    padv = max(1.0, (mx - mn) * 0.18)
    bottom = mn - padv
    ax.set_ylim(bottom, mx + padv)

    # Ночная заливка на 24ч-графиках (по сегодняшнему восходу/закату)
    if mode in ('daily', 'pres24', 'forecast'):
        sr, ss = sun_times(datetime.date.today())
        sr_h, ss_h = int(sr[:2]), int(ss[:2])
        for i, r in enumerate(rows):
            hh = int(str(r[1])[:2])
            if hh < sr_h or hh >= ss_h:
                ax.axvspan(i - 0.5, i + 0.5, color='#000000', alpha=0.30, zorder=0)

    sm = _smooth(data, 3 if len(data) >= 6 else 1)
    ax.plot(x, data, color=line_color, linewidth=1.4, alpha=0.30, zorder=2)
    ax.plot(x, sm, color=line_color, linewidth=3.0, zorder=4,
            solid_capstyle='round', solid_joinstyle='round')
    _gradient_fill(ax, x, sm, line_color, bottom)

    i_min, i_max = data.index(mn), data.index(mx)
    ax.scatter([i_min], [mn], color='#f87171', s=42, zorder=6, edgecolors=BG, linewidths=1.2)
    ax.scatter([i_max], [mx], color='#34d399', s=42, zorder=6, edgecolors=BG, linewidths=1.2)
    ax.annotate(f"▼ {mn}{unit}", (i_min, mn), xytext=(0, -16),
                textcoords="offset points", ha='center', color='#f87171', fontsize=9)
    ax.annotate(f"▲ {mx}{unit}", (i_max, mx), xytext=(0, 10),
                textcoords="offset points", ha='center', color='#34d399', fontsize=9)

    # Правые оси: влажность (24ч/прогноз) / давление (неделя)
    if mode in ('daily', 'forecast') and hum and all(v is not None and v == v for v in hum):
        ax2 = ax.twinx()
        ax2.plot(x, [round(v, 1) for v in hum], color='#34d399', linewidth=1.6,
                 linestyle='--', alpha=0.85, zorder=3)
        ax2.set_ylabel('Влажность, %', color='#34d399')
        ax2.tick_params(axis='y', colors='#34d399', labelsize=9)
        ax2.set_ylim(0, 100)
        ax2.spines['right'].set_color(GRID)
    elif mode == 'weekly':
        pv = [r[2] for r in rows]
        if all(v is not None and v == v for v in pv):
            ax2 = ax.twinx()
            ax2.plot(x, [round(v, 1) for v in pv], color='#8fa2b5', linewidth=1.4,
                     linestyle=':', alpha=0.9, zorder=3)
            ax2.set_ylabel('Давление, мм', color='#8fa2b5')
            ax2.tick_params(axis='y', colors='#8fa2b5', labelsize=9)
            ax2.spines['right'].set_color(GRID)

    ax.spines['top'].set_visible(False)
    ax.spines['left'].set_color(GRID)
    ax.spines['bottom'].set_color(GRID)
    if ax2 is None:
        ax.spines['right'].set_visible(False)

    step = max(1, len(x) // 12)
    ax.set_xticks(x[::step])
    ax.set_xticklabels([labels[i] for i in x[::step]], rotation=45, ha='right', fontsize=9)
    ax.tick_params(axis='x', colors=TXT)
    ax.tick_params(axis='y', colors=TXT, labelsize=9)
    ax.grid(True, color=GRID, linestyle=':', linewidth=0.8, alpha=0.8)
    ax.set_axisbelow(True)

    plt.title(f"Солигорск: {label}", color=TXT, pad=15, fontsize=14, weight='bold')
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', facecolor=BG)
    plt.close(fig)
    return buf.getvalue()


def _render_chart_sync(rows, mode, label) -> Optional[bytes]:
    with _PLT_LOCK:
        return _render_chart_locked(rows, mode, label)


def _render_empty_sync(label: str) -> bytes:
    with _PLT_LOCK:
        plt.style.use('default')
        fig, ax = plt.subplots(figsize=(12, 6), dpi=120)
        BG, TXT = '#0f1419', '#c0c8d1'
        fig.patch.set_facecolor(BG)
        ax.set_facecolor(BG)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_color('#1e2734')
        ax.text(0.5, 0.56, "Нет данных за период", ha='center', va='center',
                color=TXT, fontsize=16, weight='bold', transform=ax.transAxes)
        ax.text(0.5, 0.46, "включи «Графики: тест» в админке или дождись замеров станции",
                ha='center', va='center', color='#7a8590', fontsize=10, transform=ax.transAxes)
        ax.set_title(label, color=TXT, pad=15, fontsize=14, weight='bold')
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png', facecolor=BG)
        plt.close(fig)
        return buf.getvalue()


def _render_ref_sync(rows) -> Optional[bytes]:
    with _PLT_LOCK:
        return _render_ref_locked(rows)


def _render_ref_locked(rows) -> Optional[bytes]:
    """Сверка с официальной: rows = (метка, наша T, официальная T).
    None-значения рисуются как разрывы линии."""
    if not rows:
        return None
    plt.style.use('default')
    fig, ax = plt.subplots(figsize=(12, 6), dpi=120)
    BG, TXT, GRID = '#0f1419', '#c0c8d1', '#1e2734'
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)

    labels = [r[0] for r in rows]
    ours = [r[1] for r in rows]
    refv = [r[2] for r in rows]
    vals = [v for v in (ours + refv) if v is not None]
    if not vals:
        plt.close(fig)
        return None
    mn, mx = min(vals), max(vals)
    padv = max(1.0, (mx - mn) * 0.18)
    ax.set_ylim(mn - padv, mx + padv)

    x = list(range(len(rows)))
    ax.plot(x, refv, color='#e8b339', linewidth=1.8, linestyle='--',
            zorder=3, label='Open-Meteo (официальная)')
    ax.plot(x, ours, color='#0ea5e9', linewidth=2.6,
            zorder=4, solid_capstyle='round', label='Станция «Солигорск»')

    ax.spines['top'].set_visible(False)
    ax.spines['left'].set_color(GRID)
    ax.spines['bottom'].set_color(GRID)
    ax.spines['right'].set_visible(False)

    # Метки оси X — на границах суток (00ч), иначе при почасовых данных
    # прореживание «каждая N-я точка» даёт плавающие часы (00ч/16ч/08ч),
    # которые читаются как беспорядок.
    midnight = [i for i, l in enumerate(labels) if l.endswith(' 00ч')]
    if len(midnight) >= 4:
        tick_idx = midnight
        tick_lab = [labels[i].split(' ')[0] for i in midnight]      # «23.11»
    else:
        half = [i for i, l in enumerate(labels)
                if l.endswith(' 00ч') or l.endswith(' 12ч')]
        if len(half) >= 4:
            tick_idx = half
            tick_lab = [labels[i] for i in half]                     # «23.11 00ч/12ч»
        else:
            step = max(1, len(x) // 12)
            tick_idx = x[::step]
            tick_lab = [labels[i] for i in tick_idx]
    ax.set_xticks(tick_idx)
    ax.set_xticklabels(tick_lab, rotation=45, ha='right', fontsize=9)
    ax.tick_params(axis='x', colors=TXT)
    ax.tick_params(axis='y', colors=TXT, labelsize=9)
    ax.grid(True, color=GRID, linestyle=':', linewidth=0.8, alpha=0.8)
    ax.set_axisbelow(True)

    leg = ax.legend(loc='upper left', fontsize=10, framealpha=0.15)
    for t in leg.get_texts():
        t.set_color(TXT)
    plt.title("Солигорск: сверка с официальной температурой",
              color=TXT, pad=15, fontsize=14, weight='bold')
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', facecolor=BG)
    plt.close(fig)
    return buf.getvalue()


OM_CHART_SQL = {
    'daily': """
        SELECT strftime('%d', ts) AS d,
               strftime('%H:00', ts) AS h,
               AVG(ref), AVG(hum), MIN(ts) AS ts
        FROM ref_checks
        WHERE ts > datetime('now', '-24 hours') AND ts <= datetime('now')
          AND ref IS NOT NULL
        GROUP BY d, h ORDER BY MIN(ts) ASC
    """,
    'weekly': """
        SELECT strftime('%d.%m', ts) AS d, AVG(ref), AVG(pres)
        FROM ref_checks
        WHERE ts > datetime('now', '-7 days') AND ts <= datetime('now')
          AND ref IS NOT NULL
        GROUP BY d ORDER BY MIN(ts) ASC
    """,
    'monthly': """
        SELECT strftime('%d.%m', ts) AS d, AVG(ref)
        FROM ref_checks
        WHERE ts > datetime('now', '-30 days') AND ts <= datetime('now')
          AND ref IS NOT NULL
        GROUP BY d ORDER BY MIN(ts) ASC
    """,
    'dew': """
        SELECT strftime('%d.%m', ts) AS d, AVG(ref), AVG(hum)
        FROM ref_checks
        WHERE ts > datetime('now', '-7 days') AND ts <= datetime('now')
          AND ref IS NOT NULL AND hum IS NOT NULL
        GROUP BY d ORDER BY MIN(ts) ASC
    """,
    'forecast': """
        SELECT strftime('%d', ts) AS d,
               strftime('%H:00', ts) AS h,
               AVG(ref), AVG(hum), MIN(ts) AS ts
        FROM ref_checks
        WHERE ts > datetime('now') AND ts <= datetime('now', '+24 hours')
          AND ref IS NOT NULL
        GROUP BY d, h ORDER BY MIN(ts) ASC
    """,
}


def _om_chart_rows_sync(mode: str) -> list:
    """Ряды графика из эталона Open-Meteo (та же форма, что у станционных)."""
    try:
        return _postprocess_rows(mode, _db_query_sync(OM_CHART_SQL[mode], fetch=True) or [])
    except Exception:
        logger.exception("Ошибка выборки Open-Meteo для графика %s", mode)
        return []


def _chart_rows_sync(mode: str) -> list:
    """Синхронная выборка для Flask-потока."""
    try:
        return _postprocess_rows(mode, _db_query_sync(CHART_SQL[mode], fetch=True) or [])
    except Exception:
        logger.exception("Ошибка выборки для графика %s", mode)
        return []


async def create_chart(mode: str, label: str) -> Optional[io.BytesIO]:
    """График для бота (с кэшем). В om-режиме данные — из ref_checks.
    Прогноз всегда из ref_checks: его источник только Open-Meteo."""
    om = get_data_source() == 'om' or mode == 'forecast'
    key = (mode, TEST_MODE, om)
    cached = _chart_cache_get(key)
    if cached:
        return io.BytesIO(cached)
    if TEST_MODE:
        rows = get_test_chart_data(mode)
    elif om:
        rows = _om_chart_rows_sync(mode)
        label += ' · Open-Meteo'
    else:
        rows = _postprocess_rows(mode, await execute_query(CHART_SQL[mode], fetch=True) or [])
    if not rows:
        return None
    png = await asyncio.to_thread(_render_chart_sync, rows, mode, label)
    if png:
        _chart_cache_put(key, png)
        return io.BytesIO(png)
    return None

# ==================== МИНИМАЛЬНЫЙ XLSX (без openpyxl) ====================
def _xml_escape(s: str) -> str:
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _col_letter(idx: int) -> str:
    letters = ''
    while idx:
        idx, rem = divmod(idx - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def make_xlsx_bytes(header: List[str], rows: List[Tuple]) -> io.BytesIO:
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


def _export_rows_sync(days: int = 7) -> list:
    return _db_query_sync(
        f"""SELECT datetime(timestamp, '{TIMEZONE_OFFSET}'), temp, hum, pres
            FROM weather_data WHERE timestamp > datetime('now', '-{days} days')
            ORDER BY timestamp ASC""", fetch=True) or []


def make_csv_bytes(rows: list) -> io.BytesIO:
    """CSV с BOM и ';' — Excel открывает по-русски сразу."""
    buf = io.StringIO()
    buf.write('Время;Температура °C;Влажность %;Давление мм\n')
    for r in rows:
        buf.write(f"{r[0]};{fmt_num(r[1])};{fmt_num(r[2])};{fmt_num(r[3])}\n")
    return io.BytesIO(b'\xef\xbb\xbf' + buf.getvalue().encode('utf-8'))

# ==================== ГЛОБАЛЬНЫЙ ОБРАБОТЧИК ОШИБОК ====================
@dp.errors()
async def on_error(update: types.Update, exception: Exception) -> bool:
    logger.exception(f"Необработанная ошибка в update {update.update_id}: {exception}")
    return True

# ==================== ОСНОВНЫЕ ХЕНДЛЕРЫ ====================
@dp.message(F.text == "/start")
async def cmd_start(message: types.Message) -> None:
    await register_user(message.from_user.id, message.from_user.first_name,
                        message.from_user.username)
    await message.answer(
        "👋 Метеостанция «Солигорск» (TestV4) готова!\n\n"
        "🌡 Погода • 📅 Сводка • 📊 Графики и рекорды • 💧 Точка росы\n"
        "🔮 Прогноз • 🧥 Как одеться • 🏆 Рекорды\n"
        "Алерты: тишина / датчик / скачок T / мороз / жара / туман / дайджест 21:00",
        reply_markup=main_kb
    )


@dp.message(F.text == "/id")
@dp.message(F.text == "🪪 Мой ID")
async def cmd_id(message: types.Message) -> None:
    await register_user(message.from_user.id, message.from_user.first_name,
                        message.from_user.username)
    await message.answer(f"🆔 Твой Telegram ID: `{message.from_user.id}`", parse_mode="Markdown")


@dp.message(F.text == "/promo")
@dp.message(F.text == "ℹ️ Фичи")
async def cmd_promo(message: types.Message) -> None:
    await message.answer(
        "ℹ️ TestV4 — что есть:\n"
        "• ключ и валидация на /update — мусор в БД не попадёт\n"
        "• алерты: тишина, ошибка датчика, скачок T, мороз, жара,\n"
        "  риск тумана, дневной дайджест 21:00, итоги недели\n"
        "• точка росы, «ощущается как», тренд давления, восход/закат\n"
        "• 🔮 локальный прогноз и 🧥 «как одеться» (офлайн-эвристики)\n"
        "• 🏆 абсолютные рекорды за всю историю\n"
        "• графики V4: сглаживание, градиент, ночные часы,\n"
        "  давление на неделе, кэш PNG\n"
        "• прогноз 24ч: график будущих часов из Open-Meteo\n"
        "• ночные бэкапы + «Бэкап сейчас» файлом, экспорт CSV/Excel\n"
        "• /alert — труба алертов из прошивки ESP32"
    )


@dp.message(F.text == ADMIN_PASS)
async def dev_login(message: types.Message) -> None:
    await register_user(message.from_user.id, message.from_user.first_name,
                        message.from_user.username)
    _admin_uids.add(message.from_user.id)
    await message.answer("🔓 Режим администратора.", reply_markup=get_admin_kb())


@dp.message(F.text == "/web")
@dp.message(F.text == "🖥 Веб-админка")
async def cmd_web_admin(message: types.Message) -> None:
    if message.from_user.id not in _admin_uids:
        return
    urls = [f"http://localhost:{WEB_PORT}{WEB_ADMIN_PATH}"]
    lan = f"http://{lan_ip()}:{WEB_PORT}{WEB_ADMIN_PATH}"
    if lan not in urls:
        urls.append(lan)
    lines = ["🖥 Веб-админка станции:", ""]
    lines.append(f"• {urls[0]} — на машине, где крутится бот")
    if len(urls) > 1:
        lines.append(f"• {urls[1]} — с телефона в той же Wi-Fi сети")
    await message.answer("\n".join(lines))


@dp.message(F.text == "🔔 Алерты")
async def alerts_menu(message: types.Message) -> None:
    if message.from_user.id not in _admin_uids:
        return
    await message.answer("🔔 Алерты — нажми на строку, чтобы включить/выключить "
                         "(✅ = включён, ❌ = выключен):",
                         reply_markup=get_alerts_kb())


@dp.message(F.text.in_(ALERT_BTN_TEXTS))
async def alert_toggle_handler(message: types.Message) -> None:
    if message.from_user.id not in _admin_uids:
        return
    label = (message.text or '')[2:].strip()  # срезаем "✅ "/"❌ "
    kind = next((k for k, v in ALERT_KINDS.items() if v == label), None)
    if kind is None:
        return
    key = 'alert_' + kind
    now_on = get_setting(key, '1') == '1'
    set_setting(key, '0' if now_on else '1')
    state = 'включён' if not now_on else 'выключен'
    await message.answer(f"🔔 Алерт «{label}» {state}.", reply_markup=get_alerts_kb())


@dp.message(F.text == "↩️ Назад к админке")
async def alerts_back(message: types.Message) -> None:
    if message.from_user.id not in _admin_uids:
        return
    await message.answer("Админка:", reply_markup=get_admin_kb())


@dp.message(F.text.in_({"📡 Источник: станция", "📡 Источник: Open-Meteo"}))
async def toggle_data_source_handler(message: types.Message) -> None:
    """Тумблер источника данных: только для админов, вошедших по паролю."""
    if message.from_user.id not in _admin_uids:
        return
    new_mode = await toggle_data_source()
    name = "Open-Meteo" if new_mode == 'om' else "метеостанция"
    await message.answer(f"📡 Источник данных бота: {name}.\n"
                         f"«Погода сейчас», точка росы, «как одеться» и графики "
                         f"теперь берут данные {('из Open-Meteo' if new_mode == 'om' else 'со станции')}.",
                         reply_markup=get_admin_kb())


@dp.message(F.text == "Назад")
async def go_back(message: types.Message) -> None:
    await message.answer("Главное меню", reply_markup=main_kb)


@dp.message(F.text == "Погода сейчас")
async def weather_now(message: types.Message) -> None:
    await register_user(message.from_user.id, message.from_user.first_name,
                        message.from_user.username)
    if TEST_MODE:
        t, h, p = get_test_current_weather()
        dp_v = dew_point(t, h)
        feels = apparent_temp(t, h)
        await message.answer(f"🌡 Температура: {t}°C\n🌡 Ощущается как: {feels}°C\n"
                             f"💧 Влажность: {h}%\n☁️ Давление: {p} мм\n"
                             f"💧 Точка росы: {dp_v}°C\n⏱ Замер: только что (TEST)")
        return
    text = await weather_now_text()
    await message.answer(text if text else "📡 Данных нет.")


@dp.message(F.text == "🔮 Прогноз")
async def local_forecast(message: types.Message) -> None:
    await register_user(message.from_user.id, message.from_user.first_name,
                        message.from_user.username)
    await message.answer(await forecast_text(), parse_mode="Markdown")
    # График прогноза всегда из Open-Meteo (ref_checks), независимо от тумблера
    buf = await create_chart('forecast', CHART_LABELS['forecast'])
    if buf:
        await message.answer_photo(BufferedInputFile(buf.read(), "forecast.png"))


@dp.message(F.text == "🧥 Как одеться")
async def dress_handler(message: types.Message) -> None:
    await register_user(message.from_user.id, message.from_user.first_name,
                        message.from_user.username)
    if TEST_MODE:
        t, h, _ = get_test_current_weather()
        await message.answer(f"🧥 **Как одеться:**\n{dress_advice(t, h)}", parse_mode="Markdown")
        return
    # om-режим: температура и влажность из Open-Meteo
    if get_data_source() == 'om':
        disp = await get_display_temp()
        cur = await asyncio.to_thread(_openmeteo_current_sync)
        if disp is None or not cur or cur.get('hum') is None:
            await message.answer("🌐 Open-Meteo недоступен.")
            return
        await message.answer(
            f"🧥 **Как одеться (по официальным данным):**\n{dress_advice(disp['blended'], cur['hum'])}",
            parse_mode="Markdown")
        return
    res = await execute_query(
        "SELECT temp, hum FROM weather_data ORDER BY id DESC LIMIT 1", fetch_one=True)
    disp = await get_display_temp()
    if disp is None or (not res or res[1] is None):
        await message.answer("📡 Данных нет.")
        return
    await message.answer(f"🧥 **Как одеться:**\n{dress_advice(disp['blended'], res[1])}",
                         parse_mode="Markdown")


@dp.message(F.text == "🏆 Рекорды")
async def all_records(message: types.Message) -> None:
    await register_user(message.from_user.id, message.from_user.first_name,
                        message.from_user.username)
    await message.answer(await records_text(), parse_mode="Markdown")


@dp.message(F.text == "💧 Точка росы")
async def dew_only(message: types.Message) -> None:
    await register_user(message.from_user.id, message.from_user.first_name,
                        message.from_user.username)
    if TEST_MODE:
        t, h, _ = get_test_current_weather()
        await message.answer(f"💧 Точка росы: {dew_point(t, h)}°C (TEST)")
        return
    # om-режим: T и H из Open-Meteo
    if get_data_source() == 'om':
        cur = await asyncio.to_thread(_openmeteo_current_sync)
        if not cur or cur.get('hum') is None or cur.get('temp') is None:
            await message.answer("🌐 Open-Meteo недоступен.")
            return
        dp_v = dew_point(cur['temp'], cur['hum'])
        hint = ""
        if dp_v is not None and cur['temp'] - dp_v < 2.0:
            hint = "\n⚠️ T близко к точке росы — риск конденсата/инея."
        await message.answer(f"💧 Точка росы (официальные данные): {dp_v}°C\n"
                             f"🌡 текущая: {cur['temp']}°C, влажность: {cur['hum']}%{hint}")
        return
    res = await execute_query(
        "SELECT temp, hum FROM weather_data WHERE temp IS NOT NULL AND hum IS NOT NULL "
        "ORDER BY id DESC LIMIT 1", fetch_one=True)
    disp = await get_display_temp()
    if (not res or res[1] is None) or disp is None:
        await message.answer("📡 Данных нет.")
        return
    t_show = disp['blended']
    dp_v = dew_point(t_show, res[1])
    hint = ""
    if dp_v is not None and t_show - dp_v < 2.0:
        hint = "\n⚠️ T близко к точке росы — риск конденсата/инея."
    await message.answer(f"💧 Точка росы: {dp_v}°C\n🌡 текущая: {t_show}°C, "
                         f"влажность: {res[1]}%{hint}")


@dp.message(F.text == "📊 Статистика")
async def quick_stats(message: types.Message) -> None:
    await register_user(message.from_user.id, message.from_user.first_name,
                        message.from_user.username)
    if TEST_MODE:
        await message.answer("📊 Статистика (TEST): 24ч 5…20°C, 7д 1…22°C, 30д −3…24°C")
        return
    # om-режим: статистика по официальным данным из ref_checks (жмёт 7 дней)
    if get_data_source() == 'om':
        lines = ["📊 **Статистика (официальные данные Open-Meteo):**\n"]
        for title, where in (("24 часа:",
                              "ts > datetime('now', '-1 day') AND ts <= datetime('now')"),
                             ("7 дней:",
                              "ts > datetime('now', '-7 days') AND ts <= datetime('now')")):
            s = await execute_query(
                f"""SELECT MIN(ref), MAX(ref), ROUND(AVG(ref), 1), COUNT(*)
                    FROM ref_checks WHERE {where} AND ref IS NOT NULL""",
                fetch_one=True)
            if s and s[0] is not None:
                lines.append(f"• {title} {s[0]}…{s[1]}°C (ср {s[2]}, часов {s[3]})")
            else:
                lines.append(f"• {title} данных нет")
        lines.append("• 30 дней: копится с момента включения om-режима")
        await message.answer("\n".join(lines), parse_mode="Markdown")
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
    await register_user(message.from_user.id, message.from_user.first_name,
                        message.from_user.username)
    await message.answer(await get_daily_summary_text(), parse_mode="Markdown")


@dp.message(F.text == "Погода за период")
async def select_period(message: types.Message) -> None:
    await message.answer("Выберите тип графика:", reply_markup=period_kb)


PERIOD_MAP = {
    'За 24 часа': ('daily', CHART_LABELS['daily']),
    'За неделю': ('weekly', CHART_LABELS['weekly']),
    'За месяц': ('monthly', CHART_LABELS['monthly']),
    'Давление 24ч': ('pres24', CHART_LABELS['pres24']),
}


@dp.message(F.text.in_(PERIOD_MAP.keys()))
async def charts(message: types.Message) -> None:
    await register_user(message.from_user.id, message.from_user.first_name,
                        message.from_user.username)
    mode, label = PERIOD_MAP[message.text]
    buf = await create_chart(mode, label)
    if buf:
        await message.answer_photo(BufferedInputFile(buf.read(), "chart.png"))
    else:
        await message.answer("📉 Мало данных.")


@dp.message(F.text == "Точка росы (неделя)")
async def chart_dew(message: types.Message) -> None:
    await register_user(message.from_user.id, message.from_user.first_name,
                        message.from_user.username)
    buf = await create_chart('dew', CHART_LABELS['dew'])
    if buf:
        await message.answer_photo(BufferedInputFile(buf.read(), "dew.png"))
    else:
        await message.answer("📉 Мало данных.")

# ==================== РЕКОРДЫ 24Ч ====================
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
    await register_user(message.from_user.id, message.from_user.first_name,
                        message.from_user.username)
    metric, order, tmpl = LIMITS[message.text]
    if TEST_MODE:
        value, ts = get_test_limit(TEST_LIMIT_MAP[message.text])
        await message.answer(tmpl.format(v=value, t=ts), parse_mode="Markdown")
        return
    res = await execute_query(
        f"""SELECT {metric}, strftime('%H:%M', datetime(timestamp, '{TIMEZONE_OFFSET}'))
            FROM weather_data
            WHERE timestamp > datetime('now', '-24 hours') AND {metric} IS NOT NULL
            ORDER BY {metric} {order} LIMIT 1""",
        fetch_one=True)
    if res:
        await message.answer(tmpl.format(v=res[0], t=res[1]), parse_mode="Markdown")
    else:
        await message.answer("📉 Данных за 24 часа нет.")


@dp.message(F.text == "Пределы 24ч")
async def show_limits_kb(message: types.Message) -> None:
    await message.answer("Рекорды за последние 24 часа:", reply_markup=limits_kb)

# ==================== ХЕНДЛЕРЫ РАЗРАБОТЧИКА ====================
@dp.message(F.text == "📊 Статус системы")
async def sys_status(message: types.Message) -> None:
    disk = psutil.disk_usage(DISK_PATH)
    stats = await execute_query(
        f"SELECT COUNT(*), IFNULL(datetime(MAX(timestamp), '{TIMEZONE_OFFSET}'), 'Нет') "
        f"FROM weather_data", fetch_one=True)
    db_size = os.path.getsize(DB_NAME) / 1024 / 1024
    backup_count = len([f for f in os.listdir(BACKUP_DIR) if f.endswith('.db')]) \
        if os.path.isdir(BACKUP_DIR) else 0
    mem = psutil.virtual_memory()
    now = time.time()
    rejects_24h = len([s for s in reject_stamps if now - s <= 24 * 3600])
    await message.answer(
        f"🖥 **System Status (TestV4)**\n━━━━━━━━━━━━\n"
        f"📅 Последняя запись: `{stats[1]}`\n"
        f"📈 Всего записей: `{stats[0]}`\n"
        f"🚫 Отказов /update за 24ч: `{rejects_24h}`\n"
        f"💾 Диск свободно: `{round(disk.free / 1024**3, 2)} GB`\n"
        f"🧠 RAM занято: `{mem.percent}%`\n"
        f"🗄 БД: `{round(db_size, 1)} MB`, бэкапов: `{backup_count}`\n"
        f"⏱ Uptime бота: `{human_dh(time.time() - BOT_START_TIME)}`\n"
        f"🏁 Бот стартовал: `{BOT_STARTED_AT_STR}`\n"
        f"🔇 Watchdog: `{SILENCE_LIMIT_MIN} мин`\n"
        f"🥶 Мороз: `{FROST_THRESHOLD_C}°C` 🔥 Жара: `{HEAT_THRESHOLD_C}°C` "
        f"⬆️ Скачок: `{JUMP_LIMIT_C}°C/30мин`\n"
        f"🌫 Туман-алерт: `T−Tdew<{FOG_DEW_GAP_C}°C`\n"
        f"🧪 Test Mode: `{'ВКЛ' if TEST_MODE else 'ВЫКЛ'}` "
        f"🛠 Перерыв: `{'ДА' if MAINTENANCE else 'НЕТ'}`",
        parse_mode="Markdown")


@dp.message(F.text == "📈 Аналитика")
async def analytics(message: types.Message) -> None:
    lines = ["📈 **Аналитика:**\n"]
    for title, days in (("24 часа", 1), ("7 дней", 7), ("30 дней", 30)):
        s = await execute_query(
            f"""SELECT MIN(temp), MAX(temp), ROUND(AVG(temp), 1), COUNT(*)
                FROM weather_data
                WHERE timestamp > datetime('now', '-{days} days') AND temp IS NOT NULL""",
            fetch_one=True)
        if s and s[0] is not None:
            lines.append(f"• {title}: {s[0]}…{s[1]}°C (ср {s[2]}, замеров {s[3]})")
        else:
            lines.append(f"• {title}: данных нет")
    await message.answer("\n".join(lines), parse_mode="Markdown")


@dp.message(F.text == "🌡 CPU и RAM")
async def cpu_ram(message: types.Message) -> None:
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    temp_str = ""
    try:
        temps = psutil.sensors_temps()
        for _, entries in temps.items():
            if entries:
                temp_str = f"\n🌡 CPU: `{entries[0].current}°C`"
                break
    except Exception:
        pass
    await message.answer(f"🌡 CPU: `{cpu}%`\n🧠 RAM: `{mem.percent}%` "
                         f"({round(mem.used / 1048576)} / {round(mem.total / 1048576)} МБ)"
                         f"{temp_str}", parse_mode="Markdown")


@dp.message(F.text == "🕒 Последние данные")
async def last_rows(message: types.Message) -> None:
    rows = await execute_query(
        f"""SELECT datetime(timestamp, '{TIMEZONE_OFFSET}'), temp, hum, pres
            FROM weather_data ORDER BY id DESC LIMIT 5""", fetch=True)
    if not rows:
        await message.answer("📡 Данных нет.")
        return
    lines = ["🕒 **Последние записи:**"]
    for r in rows:
        lines.append(f"`{r[0]}` → `{fmt_num(r[1])}°C / {fmt_num(r[2])}% / {fmt_num(r[3])} мм`")
    await message.answer("\n".join(lines), parse_mode="Markdown")


@dp.message(F.text == "📦 Экспорт CSV")
async def export_csv_bot(message: types.Message) -> None:
    rows = await asyncio.to_thread(_export_rows_sync, 7)
    if not rows:
        await message.answer("📉 Данных за 7 дней нет.")
        return
    buf = make_csv_bytes(rows)
    await message.answer_document(BufferedInputFile(buf.getvalue(), "weather_7days.csv"))


@dp.message(F.text == "📊 Экспорт Excel")
async def export_xlsx_bot(message: types.Message) -> None:
    rows = await asyncio.to_thread(_export_rows_sync, 7)
    if not rows:
        await message.answer("📉 Данных за 7 дней нет.")
        return
    data = [(r[0], r[1], r[2], None if (r[3] is None or (
        isinstance(r[3], float) and math.isnan(r[3]))) else r[3]) for r in rows]
    buf = make_xlsx_bytes(['Время', 'Температура °C', 'Влажность %', 'Давление, мм'], data)
    await message.answer_document(BufferedInputFile(buf.read(), "weather_7days.xlsx"))


@dp.message(F.text == "💾 Бэкап сейчас")
async def backup_now(message: types.Message) -> None:
    name = await asyncio.to_thread(backup_db_sync)
    if not name:
        await message.answer("🔥 Бэкап не удался, смотри логи.")
        return
    with open(name, 'rb') as f:
        await message.answer_document(
            BufferedInputFile(f.read(), os.path.basename(name)),
            caption=f"💾 Бэкап создан: `{os.path.basename(name)}`", parse_mode="Markdown")


@dp.message(F.text == "✍️ Внести данные")
async def manual_input_start(message: types.Message, state: FSMContext) -> None:
    await state.set_state(DevStates.waiting_for_manual_data)
    await message.answer("✍️ Отправь значения через пробел: `t h p`\n"
                         "Например: `21.4 64 746.2` (p можно пропустить)",
                         parse_mode="Markdown")


@dp.message(DevStates.waiting_for_manual_data)
async def manual_input_process(message: types.Message, state: FSMContext) -> None:
    parts = (message.text or '').replace(',', '.').split()
    try:
        t, h = float(parts[0]), float(parts[1])
        p = float(parts[2]) if len(parts) > 2 else None
    except (IndexError, ValueError):
        await message.answer("⚠️ Не понял. Формат: `t h p`, например `21.4 64 746.2`. "
                             "Или /cancel.", parse_mode="Markdown")
        return
    await execute_query("INSERT INTO weather_data (temp, hum, pres) VALUES (?, ?, ?)", (t, h, p))
    invalidate_chart_cache()
    await state.clear()
    await message.answer(f"✅ Внесено: `{t}°C / {h}% / {fmt_num(p)} мм`",
                         parse_mode="Markdown")


@dp.message(F.text == "🧹 Очистить БД")
async def clear_db_ask(message: types.Message, state: FSMContext) -> None:
    await state.set_state(DevStates.waiting_for_clear_confirm)
    await message.answer("⚠️ Удалить ВСЕ записи измерений? Отправь `ДА` для подтверждения "
                         "или что угодно другое для отмены.", parse_mode="Markdown")


@dp.message(DevStates.waiting_for_clear_confirm)
async def clear_db_confirm(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    if (message.text or '').strip().upper() == 'ДА':
        await execute_query("DELETE FROM weather_data")
        invalidate_chart_cache()
        await message.answer("🧹 База очищена.")
    else:
        await message.answer("Отменено.")


@dp.message(F.text == "🛠 Тех. перерыв")
async def maintenance_on(message: types.Message) -> None:
    global MAINTENANCE
    MAINTENANCE = True
    await message.answer("🛠 Технический перерыв ВКЛЮЧЁН. Бот отвечает заглушкой.")


@dp.message(F.text == "✅ Возобновить")
async def maintenance_off(message: types.Message) -> None:
    global MAINTENANCE
    MAINTENANCE = False
    await message.answer("✅ Бот возобновил работу.", reply_markup=get_admin_kb())


@dp.message(F.text.in_({"🧪 Тест без БД: ВЫКЛ", "🧪 Тест без БД: ВКЛ"}))
async def toggle_test_mode(message: types.Message) -> None:
    global TEST_MODE
    TEST_MODE = not TEST_MODE
    invalidate_chart_cache()
    await message.answer(f"🧪 Тест-режим (без БД): {'ВКЛ' if TEST_MODE else 'ВЫКЛ'}",
                         reply_markup=get_admin_kb())


@dp.message(F.text == "🚪 Выход")
async def admin_exit(message: types.Message) -> None:
    await message.answer("🚪 Вышел из режима администратора.", reply_markup=main_kb)

# ==================== ВЕБ-АДМИНКА ====================
def _web_authed() -> bool:
    tok = request.cookies.get(ADMIN_COOKIE)
    if not tok:
        return False
    exp = WEB_SESSIONS.get(tok)
    if not exp:
        return False
    if time.time() > exp:
        WEB_SESSIONS.pop(tok, None)
        return False
    return True


def _station_state() -> Tuple[bool, str]:
    """(онлайн?, возраст замера) — синхронно для Flask."""
    try:
        r = _db_query_sync("SELECT MAX(timestamp) FROM weather_data", fetch_one=True)
        last = _parse_db_ts(r[0]) if r and r[0] else None
        if not last:
            return False, "—"
        age_s = max(0.0, (datetime.datetime.utcnow() - last).total_seconds())
        age = "только что" if age_s < 90 else human_dh(age_s)
        return age_s <= SILENCE_LIMIT_MIN * 60, age
    except Exception:
        return False, "—"


def _common_ctx(active: str) -> dict:
    online, age = _station_state()
    r = _db_query_sync("SELECT COUNT(*) FROM users", fetch_one=True)
    return dict(active=active,
                uptime=human_dh(time.time() - BOT_START_TIME),
                test_mode=TEST_MODE,
                station_online=online,
                station_age=age,
                users_total=(r[0] if r else 0),
                bot_started=BOT_STARTED_AT_STR)


def _period_stats(days: int) -> Tuple:
    r = _db_query_sync(
        f"""SELECT MIN(temp), MAX(temp), AVG(temp), COUNT(*) FROM weather_data
            WHERE timestamp > datetime('now', '-{days} days') AND temp IS NOT NULL""",
        fetch_one=True)
    if not r or r[0] is None:
        return (None, None, None, 0)
    return (round(r[0], 1), round(r[1], 1), round(r[2], 1), r[3])


@app.route('/admin', methods=['GET', 'POST'])
def admin_index():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASS:
            tok = ''.join(random.choices('abcdef0123456789', k=48))
            WEB_SESSIONS[tok] = time.time() + WEB_SESSION_TTL_S
            resp = redirect('/admin')
            resp.set_cookie(ADMIN_COOKIE, tok, httponly=True, samesite='Lax',
                            max_age=WEB_SESSION_TTL_S)
            return resp
        return render_template('login.html')
    if not _web_authed():
        return render_template('login.html')

    demo = request.args.get('demo') == '1'
    ctx = _common_ctx('dashboard')
    row = _db_query_sync(
        f"SELECT COUNT(*), IFNULL(datetime(MAX(timestamp), '{TIMEZONE_OFFSET}'), '—') "
        f"FROM weather_data", fetch_one=True) or (0, '—')
    s24h = _db_query_sync(
        "SELECT COUNT(*) FROM weather_data WHERE timestamp > datetime('now', '-1 day')",
        fetch_one=True)
    blocked = _db_query_sync(
        "SELECT COUNT(*) FROM users WHERE IFNULL(blocked, 0) = 1", fetch_one=True)
    # last_active хранится в локальном времени: сравниваем с 'now' + смещение TZ
    active_1h = _db_query_sync(
        f"SELECT COUNT(*) FROM users WHERE last_active IS NOT NULL AND last_active != '' "
        f"AND datetime(last_active) > datetime('now', '{TIMEZONE_OFFSET}', '-1 hour')",
        fetch_one=True)
    now = time.time()
    # Дельта «наша − официальная»: среднее за час против последнего эталона
    ref_delta = None
    ref_last = _db_query_sync(
        "SELECT ref FROM ref_checks "
        "WHERE ts <= datetime('now') ORDER BY ts DESC LIMIT 1", fetch_one=True)
    ours_hour = _db_query_sync(
        "SELECT AVG(temp) FROM weather_data "
        "WHERE timestamp > datetime('now', '-1 hour') AND temp IS NOT NULL", fetch_one=True)
    if (ref_last and ref_last[0] is not None
            and ours_hour and ours_hour[0] is not None):
        ref_delta = round(ours_hour[0] - ref_last[0], 1)

    # Тренды для панели: T за час (30-мин окна), давление за 3 часа
    t_now = _db_query_sync(
        "SELECT AVG(temp) FROM weather_data "
        "WHERE timestamp > datetime('now', '-60 minutes') AND temp IS NOT NULL", fetch_one=True)
    t_prev = _db_query_sync(
        "SELECT AVG(temp) FROM weather_data "
        "WHERE timestamp BETWEEN datetime('now', '-120 minutes') "
        "AND datetime('now', '-60 minutes') AND temp IS NOT NULL", fetch_one=True)
    t_delta_1h = (round(t_now[0] - t_prev[0], 1)
                  if t_now and t_prev and t_now[0] is not None and t_prev[0] is not None
                  else None)
    pn = _db_query_sync(
        "SELECT AVG(pres) FROM weather_data "
        "WHERE timestamp > datetime('now', '-30 minutes') AND pres IS NOT NULL", fetch_one=True)
    pp = _db_query_sync(
        "SELECT AVG(pres) FROM weather_data "
        "WHERE timestamp BETWEEN datetime('now', '-210 minutes') "
        "AND datetime('now', '-180 minutes') AND pres IS NOT NULL", fetch_one=True)
    p_delta_3h = (round(pn[0] - pp[0], 1)
                  if pn and pp and pn[0] is not None and pp[0] is not None
                  else None)
    source_om = request.args.get('source') == 'om'
    ctx.update(
        total=row[0] or 0,
        last_ts=row[1] or '—',
        sensor_24h=(s24h[0] if s24h else 0),
        users_blocked=(blocked[0] if blocked else 0),
        active_1h=(active_1h[0] if active_1h else 0),
        db_size_mb=round(os.path.getsize(DB_NAME) / 1048576, 2) if os.path.exists(DB_NAME) else 0.0,
        rejects_24h=len([s for s in reject_stamps if now - s <= 24 * 3600]),
        s24=_period_stats(1), s7=_period_stats(7), s30=_period_stats(30),
        chart_demo=demo, bust=int(time.time()),
        ref_delta=ref_delta,
        t_delta_1h=t_delta_1h, p_delta_3h=p_delta_3h,
        source_om=source_om,
        esp_tel=dict(_esp_tel),
        esp_tel_age=(int(time.time() - _esp_tel['ts']) if _esp_tel['ts'] else None),
    )
    return render_template('dashboard.html', **ctx)


@app.route('/admin/logout', methods=['POST'])
def admin_logout():
    tok = request.cookies.get(ADMIN_COOKIE)
    if tok:
        WEB_SESSIONS.pop(tok, None)
    resp = redirect('/admin')
    resp.delete_cookie(ADMIN_COOKIE)
    return resp


@app.route('/admin/users')
def admin_users():
    if not _web_authed():
        return redirect('/admin')
    rows = _db_query_sync(
        "SELECT user_id, last_active, IFNULL(blocked, 0), first_name, username "
        "FROM users ORDER BY user_id",
        fetch=True) or []
    users = [{'uid': r[0],
              'act': (r[1][:16] if r[1] else '—'),
              'blocked': 1 if r[2] else 0,
              'name': r[3],
              'username': r[4]} for r in rows]
    return render_template('users.html', **_common_ctx('users'), users=users)


@app.route('/admin/activity')
def admin_activity_page():
    if not _web_authed():
        return redirect('/admin')
    return render_template('activity.html', **_common_ctx('activity'))


def _activity_snapshot() -> dict:
    """Снимок пользователей + событий за 24 ч (для JSON и SSE-старта)."""
    users = _db_query_sync(
        """SELECT user_id, IFNULL(first_name, ''), IFNULL(username, ''),
                  IFNULL(last_active, ''), IFNULL(blocked, 0)
           FROM users ORDER BY user_id""", fetch=True) or []
    ev_rows = _db_query_sync(
        f"""SELECT user_id, strftime('%H:%M', ts, '{TIMEZONE_OFFSET}')
            FROM user_events WHERE ts > datetime('now', '-1 day') ORDER BY ts""",
        fetch=True) or []
    timeline = {}
    for uid, hm in ev_rows:
        timeline.setdefault(int(uid), []).append(hm)
    out = []
    for r in users:
        uid = int(r[0])
        out.append({'uid': uid,
                    'name': r[1] or None,
                    'username': r[2] or None,
                    'act': (r[3][:16] if r[3] else '—'),
                    'blocked': 1 if r[4] else 0,
                    'times': timeline.get(uid, [])})
    snap = {'ok': True, 'users': out,
            'esp': (dict(_esp_tel) if _esp_tel['ts'] else None)}
    return snap


@app.route('/admin/activity/data')
def admin_activity_data():
    if not _web_authed():
        return Response('{"ok":false,"error":"forbidden"}',
                        mimetype='application/json', status=403)
    return Response(json.dumps(_activity_snapshot(), ensure_ascii=False),
                    mimetype='application/json')


@app.route('/admin/activity/stream')
def admin_activity_stream():
    """SSE: старт — снимок; дальше — новые события user_events по мере появления."""
    if not _web_authed():
        return Response('forbidden', status=403)

    def gen():
        last_id = 0
        r0 = _db_query_sync("SELECT COALESCE(MAX(id), 0) FROM user_events", fetch_one=True)
        if r0 and r0[0] is not None:
            last_id = int(r0[0])
        snapshot = json.dumps(_activity_snapshot(), ensure_ascii=False)
        yield "event: snapshot\ndata: " + snapshot + "\n\n"
        idle = 0
        while True:
            rows = _db_query_sync(
                "SELECT user_events.id, users.user_id, "
                "strftime('%H:%M', user_events.ts, '{0}') "
                "FROM user_events JOIN users ON users.user_id = user_events.user_id "
                "WHERE user_events.id > ? ORDER BY user_events.id".format(TIMEZONE_OFFSET),
                (last_id,), fetch=True) or []
            for rid, uid, hm in rows:
                last_id = int(rid)
                payload = json.dumps({'uid': int(uid), 'time': hm},
                                     ensure_ascii=False)
                yield "data: " + payload + "\n\n"
            idle += 1
            if idle % 15 == 0:
                yield ": keepalive\n\n"
            time.sleep(1.5)

    from flask import stream_with_context
    return Response(stream_with_context(gen()),
                    mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache',
                             'X-Accel-Buffering': 'no'})


@app.route('/admin/users/delete', methods=['POST'])
def admin_user_delete():
    if not _web_authed():
        return redirect('/admin')
    uid = request.form.get('user_id')
    if uid:
        _db_query_sync("DELETE FROM users WHERE user_id = ?", (int(uid),))
    return redirect('/admin/users')
    if not _web_authed():
        return redirect('/admin')
    uid = request.form.get('user_id')
    if uid:
        _db_query_sync("DELETE FROM users WHERE user_id = ?", (int(uid),))
        invalidate_blocked_cache()
    return redirect('/admin/users')


@app.route('/admin/users/block', methods=['POST'])
def admin_user_block():
    if not _web_authed():
        return redirect('/admin')
    uid = request.form.get('user_id')
    if uid:
        _db_query_sync("UPDATE users SET blocked = 1 WHERE user_id = ?", (int(uid),))
        invalidate_blocked_cache()
    return redirect('/admin/users')


@app.route('/admin/users/unblock', methods=['POST'])
def admin_user_unblock():
    if not _web_authed():
        return redirect('/admin')
    uid = request.form.get('user_id')
    if uid:
        _db_query_sync("UPDATE users SET blocked = 0 WHERE user_id = ?", (int(uid),))
        invalidate_blocked_cache()
    return redirect('/admin/users')


@app.route('/admin/broadcast', methods=['POST'])
def admin_broadcast():
    if not _web_authed():
        return redirect('/admin')
    text = (request.form.get('text') or '').strip()
    if text:
        web_broadcast_queue.append(text[:4000])
    return redirect('/admin/users')


@app.route('/admin/data')
def admin_data():
    if not _web_authed():
        return redirect('/admin')
    rows = _db_query_sync(
        "SELECT id, temp, hum, pres, timestamp FROM weather_data ORDER BY id DESC LIMIT 200",
        fetch=True) or []
    records = []
    for r in rows:
        dt = _parse_db_ts(r[4])
        ts_local = (dt + LOCAL_TZ_SHIFT).strftime('%Y-%m-%d %H:%M:%S') if dt else '—'
        # брак — записи ПОСЛЕ метки отказа старого датчика (как в TestV3)
        bad = bool(r[4]) and r[4] >= BAD_DATA_FROM
        records.append({'id': r[0], 't': r[1], 'h': r[2],
                        'p': fmt_num(r[3]), 'ts': ts_local, 'bad': bad})
    return render_template('data.html', **_common_ctx('data'), records=records)


@app.route('/admin/data/insert', methods=['POST'])
def admin_data_insert():
    if not _web_authed():
        return redirect('/admin')
    try:
        t = float(request.form.get('t'))
        h = float(request.form.get('h'))
        p_raw = (request.form.get('p') or '').strip().replace(',', '.')
        p = float(p_raw) if p_raw else None
        _db_query_sync("INSERT INTO weather_data (temp, hum, pres) VALUES (?, ?, ?)",
                       (t, h, p))
        invalidate_chart_cache()
    except (TypeError, ValueError):
        pass
    return redirect('/admin/data')


@app.route('/admin/data/delete', methods=['POST'])
def admin_data_delete():
    if not _web_authed():
        return redirect('/admin')
    try:
        rid = int(request.form.get('id'))
        _db_query_sync("DELETE FROM weather_data WHERE id = ?", (rid,))
        invalidate_chart_cache()
    except (TypeError, ValueError):
        pass
    return redirect('/admin/data')


@app.route('/admin/backups')
def admin_backups():
    if not _web_authed():
        return redirect('/admin')
    items = []
    if os.path.isdir(BACKUP_DIR):
        for f in os.listdir(BACKUP_DIR):
            if f.endswith('.db'):
                p = os.path.join(BACKUP_DIR, f)
                try:
                    st = os.stat(p)
                    items.append({'name': f, 'size_mb': round(st.st_size / 1048576, 2),
                                  'mtime': datetime.datetime.fromtimestamp(st.st_mtime)
                                  .strftime('%Y-%m-%d %H:%M')})
                except OSError:
                    pass
        items.sort(key=lambda x: x['mtime'], reverse=True)
    return render_template('backups.html', **_common_ctx('backups'), items=items)


@app.route('/admin/backup/create', methods=['POST'])
def admin_backup_create():
    if not _web_authed():
        return redirect('/admin')
    backup_db_sync()
    return redirect('/admin/backups')


@app.route('/admin/backups/download/<path:name>')
def admin_backup_download(name: str):
    if not _web_authed():
        return redirect('/admin')
    return send_from_directory(BACKUP_DIR, name, as_attachment=True)


@app.route('/admin/testmode', methods=['POST'])
def admin_testmode():
    global TEST_MODE
    if not _web_authed():
        return redirect('/admin')
    TEST_MODE = not TEST_MODE
    invalidate_chart_cache()
    return redirect('/admin')


@app.route('/admin/sourcetoggle', methods=['POST'])
def admin_source_toggle():
    """Глобальный переключатель источника данных: станция <-> Open-Meteo.
    Влияет на бота (Погода сейчас/точка росы/как одеться/прогноз/графики)
    и на графики админки."""
    if not _web_authed():
        return redirect('/admin')
    set_data_source('station' if get_data_source() == 'om' else 'om')
    invalidate_chart_cache()
    return redirect(request.referrer or '/admin')


@app.route('/admin/chart/<mode>')
def admin_chart(mode: str):
    if not _web_authed():
        return "Forbidden", 403
    if mode == 'ref':
        demo = request.args.get('demo') == '1'
        key = ('ref', demo or TEST_MODE)
        png = _chart_cache_get(key)
        if png is None:
            if demo or TEST_MODE:
                rows = get_test_chart_data('ref')
            else:
                ours = _db_query_sync(
                    """SELECT strftime('%Y-%m-%d %H:00:00', timestamp) AS h, AVG(temp)
                       FROM weather_data
                       WHERE timestamp > datetime('now', '-7 days') AND temp IS NOT NULL
                       GROUP BY h ORDER BY h""", fetch=True) or []
                refs = _db_query_sync(
                    """SELECT strftime('%Y-%m-%d %H:00:00', ts) AS h, ref
                       FROM ref_checks
                       WHERE ts <= datetime('now') ORDER BY h""", fetch=True) or []
                od = {r[0]: r[1] for r in ours}
                rd = {r[0]: r[1] for r in refs}
                # метки короче: «23.11 14ч»
                rows = [(f"{k[8:10]}.{k[5:7]} {k[11:13]}ч", od.get(k), rd.get(k))
                        for k in sorted(set(od) | set(rd))]
            png = (_render_ref_sync(rows) if rows
                   else _render_empty_sync(CHART_LABELS['ref']))
            if png:
                _chart_cache_put(key, png)
        resp = Response(png, mimetype='image/png')
        resp.headers['Cache-Control'] = 'no-cache'
        return resp
    m = {'24h': 'daily', '7d': 'weekly', '30d': 'monthly', 'dew': 'dew',
         'forecast': 'forecast'}.get(mode)
    if not m:
        return "Not found", 404
    demo = request.args.get('demo') == '1'
    # источник: явный параметр приоритетнее, иначе — глобальный режим бота
    if 'source' in request.args:
        source_om = request.args.get('source') == 'om'
    else:
        source_om = get_data_source() == 'om'
    key = (m, demo or TEST_MODE, source_om)
    png = _chart_cache_get(key)
    if png is None:
        if demo or TEST_MODE:
            rows = get_test_chart_data(m)
        elif source_om or m == 'forecast':
            rows = _om_chart_rows_sync(m)   # прогноз всегда из Open-Meteo
        else:
            rows = _chart_rows_sync(m)
        label = CHART_LABELS[m] + (' · Open-Meteo' if source_om or m == 'forecast' else '')
        png = (_render_chart_sync(rows, m, label) if rows
               else _render_empty_sync(label))
        if png:
            _chart_cache_put(key, png)
    resp = Response(png, mimetype='image/png')
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


_openmeteo_cur: dict = {'ts': 0.0, 'data': None}


def _openmeteo_current_sync() -> Optional[dict]:
    """Текущие условия Open-Meteo для админки: словарь с человеческими полями."""
    import urllib.request
    url = OPEN_METEO_URL + (
        '&current=temperature_2m,relative_humidity_2m,apparent_temperature,'
        'surface_pressure,precipitation,cloud_cover,'
        'wind_speed_10m,wind_direction_10m,weather_code')
    req = urllib.request.Request(url, headers={'User-Agent': 'soligorsk-meteo/1.0'})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    cur = data.get('current') or {}
    if not cur:
        return None
    press_hpa = cur.get('surface_pressure')
    wind_deg = cur.get('wind_direction_10m')
    wind_idx = int(((wind_deg % 360) + 22.5) // 45) % 8 if wind_deg is not None else None
    obs = '—'
    if cur.get('time'):
        try:
            dt = datetime.datetime.strptime(cur['time'], '%Y-%m-%dT%H:%M')
            obs = (dt + LOCAL_TZ_SHIFT).strftime('%d.%m %H:%M')
        except ValueError:
            pass
    return {
        'obs_local': obs,
        'temp': cur.get('temperature_2m'),
        'feels': cur.get('apparent_temperature'),
        'hum': cur.get('relative_humidity_2m'),
        'pressure_mm': (round(press_hpa * 760.0 / 1013.25, 1)
                        if press_hpa is not None else None),
        'precip': cur.get('precipitation'),
        'cloud': cur.get('cloud_cover'),
        'wind_ms': cur.get('wind_speed_10m'),
        'wind_dir': WIND_DIRS[wind_idx] if wind_idx is not None else '—',
        'weather': WMO_TEXT.get(cur.get('weather_code'), '—'),
    }


@app.route('/admin/openmeteo/current')
def admin_openmeteo_current():
    if not _web_authed():
        return Response('{"ok":false,"error":"forbidden"}',
                        mimetype='application/json', status=403)
    now = time.time()
    if now - _openmeteo_cur['ts'] > OPEN_METEO_CURRENT_TTL_S or not _openmeteo_cur['data']:
        try:
            _openmeteo_cur['data'] = _openmeteo_current_sync()
            _openmeteo_cur['ts'] = now
        except Exception as e:
            logger.warning("Open-Meteo current: %s", e)
    if not _openmeteo_cur['data']:
        return Response('{"ok":false,"error":"нет связи с Open-Meteo"}',
                        mimetype='application/json', status=502)
    data = dict(_openmeteo_cur['data'])
    row = _db_query_sync(
        "SELECT temp FROM weather_data WHERE temp IS NOT NULL "
        "ORDER BY id DESC LIMIT 1", fetch_one=True)
    data['station_temp'] = row[0] if row and row[0] is not None else None
    data['ok'] = True
    return Response(json.dumps(data, ensure_ascii=False), mimetype='application/json')


@app.route('/admin/export/csv')
def admin_export_csv():
    if not _web_authed():
        return redirect('/admin')
    buf = make_csv_bytes(_export_rows_sync(7))
    return Response(buf.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename=weather_7days.csv'})


@app.route('/admin/export/xlsx')
def admin_export_xlsx():
    if not _web_authed():
        return redirect('/admin')
    rows = _export_rows_sync(7)
    data = [(r[0], r[1], r[2],
             None if (r[3] is None or (isinstance(r[3], float) and math.isnan(r[3]))) else r[3])
            for r in rows]
    buf = make_xlsx_bytes(['Время', 'Температура °C', 'Влажность %', 'Давление, мм'], data)
    return Response(buf.read(),
                    mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition': 'attachment; filename=weather_7days.xlsx'})

# ==================== ЗАПУСК ====================
def run_flask() -> None:
    app.run(host='0.0.0.0', port=WEB_PORT, threaded=True, use_reloader=False, debug=False)


async def main() -> None:
    logger.info("TestV4 стартовал. Веб-админка на порту %s", WEB_PORT)
    for coro in (silence_watcher(), sensor_error_watcher(), temp_jump_watcher(),
                 frost_watcher(), heat_watcher(), fog_watcher(),
                 daily_digest_loop(), weekly_digest_loop(),
                 backup_loop(), esp_alert_watcher(), ref_watcher()):
        asyncio.create_task(coro)
    await dp.start_polling(bot)


if __name__ == "__main__":
    init_db_sync()
    Thread(target=run_flask, daemon=True).start()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Остановлен по Ctrl+C")
