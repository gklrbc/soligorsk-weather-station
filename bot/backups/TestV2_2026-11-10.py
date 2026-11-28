# TestV2 — Telegram-бот метеостанции «Солигорск»
# Развитие TestV1. Всё в одном файле, без .env — конфигурация ниже в блоке КОНФИГУРАЦИЯ.
#
# Что добавлено по сравнению с TestV1:
#   1. Секретный ключ на /update — без него посторонние не пишут мусор в БД.
#   2. Валидация данных станции: диапазонная проверка temp/hum/pres, мусор не доходит до базы.
#   3. Алерт «Станция молчит > 15 мин» + сообщение «станция вернулась» (коулдаун 1 час).
#   4. Алерт «Ошибка датчика» — если станция шлёт невалидные значения (3+ за 15 минут).
#   5. Ежедневный дайджест в 21:00 по местному (UTC+3): min/max T/H, записей, uptime.
#   6. Ночные бэкапы БД (sqlite3-backup API) с ротацией последних 7 копий.
#   7. Логи пишутся ещё и в файл logs/bot.log с ротацией по дням.
#   8. Экспорт последних 7 дней в CSV прямо в чат (админ-меню).
#   9. Рекорды пополнены: влажность и давление за 24ч, кроме температуры.
#  10. График за 30 дней («Динамика месяца»).
#  11. Статус системы расширен: RAM, CPU, размер БД, число бэкапов.
#  12. /id — узнать свой Telegram ID (пригодится для фильтров/отладки).

import asyncio
import aiosqlite
import sqlite3
import datetime
import io
import time
import os
import sys
import signal
import shutil
import random
import psutil
import logging
import logging.handlers
from typing import Optional, List, Tuple
from threading import Thread
from collections import deque
from flask import Flask, request

# Оптимизация matplotlib: работаем без монитора
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, BufferedInputFile, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramAPIError

# --- КОНФИГУРАЦИЯ ---
TOKEN = "REDACTED_OLD_BOT_TOKEN"

# TODO(пользователь): перегенерировать токен в BotFather — старый засвечен в коде/репо

# Секретный ключ /update: станция присылает /update?key=<SENSOR_KEY>&t=..&h=..&p=..
# TODO(пользователь): вписать ключ в прошивку ESP32, после включения TestV2 на бортовом
SENSOR_KEY = "REDACTED_OLD_STATION_KEY"

ADMIN_PASS = "REDACTED_OLD_ADMIN_PASS"

# ВАЖНО: Проверь путь к диску (df -h). Если диск в /media/pi/..., поменяй путь ниже.
DISK_PATH = "/mnt/weather_data"
DB_NAME = os.path.join(DISK_PATH, "weather.db")
BACKUP_DIR = os.path.join(DISK_PATH, "backups")
LOG_DIR = "logs"

TIMEZONE_OFFSET = "+3 hours"      # Солигорск (UTC+3)
LOCAL_TZ_SHIFT = datetime.timedelta(hours=3)

DIGEST_HOUR = 21                  # час суток (мест.), в который уходит дайджест
SILENCE_LIMIT_MIN = 15            # станция не писала N минут -> алерт «молчит»
CHECK_INTERVAL_S = 300            # период фоновых проверок (5 минут)
ALERT_COOLDOWN_S = 3600           # анти-флуд: не чаще раза в час на тип алерта
BACKUP_KEEP = 7                   # сколько бэкапов держать
BACKUP_INTERVAL_S = 24 * 3600     # раз в сутки

# Sanity-диапазоны входящих данных станции (вне диапазона = ошибка датчика)
TEMP_RANGE = (-60.0, 55.0)        # °C
HUM_RANGE = (0.0, 100.0)          # %
PRES_RANGE = (300.0, 1100.0)      # мм рт. ст. (399..1465 hPa)

# Граница, после которой данные в БД идут браком: отказ датчика 2026-02-15 19:20:49 мест.
BAD_DATA_FROM = "2026-02-15 16:20:49"  # по UTC, как хранится в БД

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
logger = logging.getLogger("testv2")

# --- ИНИЦИАЛИЗАЦИЯ ---
bot = Bot(token=TOKEN)
dp = Dispatcher()
app = Flask(__name__)
start_time = time.time()

# Очередь меток отклонённых /update (для алерта «ошибка датчика»), заполняется из Flask-потока
reject_stamps: deque = deque(maxlen=200)

# Таймштампы последних алертов по типам (анти-флуд)
_last_alert_at: dict = {}
# Прошла ли станция через «молчит» (для сообщения о возвращении)
silence_flag: bool = False


class DevStates(StatesGroup):
    waiting_for_manual_data = State()

# --- КЛАВИАТУРЫ ---
main_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="Погода сейчас"), KeyboardButton(text="Сводка за сегодня")],
    [KeyboardButton(text="Погода за период"), KeyboardButton(text="Пределы 24ч")],
    [KeyboardButton(text="/promo"), KeyboardButton(text="/id")]
], resize_keyboard=True)

period_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="За 24 часа"), KeyboardButton(text="За неделю")],
    [KeyboardButton(text="За месяц"), KeyboardButton(text="Назад")]
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
        [KeyboardButton(text="📦 Экспорт CSV"), KeyboardButton(text="✍️ Внести данные")],
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
    if mode == 'daily':
        now_day = datetime.datetime.now().strftime('%d')
        return [(now_day, f"{h:02d}:00", round(random.uniform(10, 20), 1), "ts") for h in range(24)]
    days = 7 if mode == 'weekly' else 30
    return [(f"{i}", round(random.uniform(5, 15), 1)) for i in range(1, days + 1)]


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

        # Миграция: колонка last_active для аналитики, если её ещё нет
        try:
            conn.execute("ALTER TABLE users ADD COLUMN last_active DATETIME DEFAULT CURRENT_TIMESTAMP")
        except sqlite3.OperationalError:
            pass  # колонка уже существует

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
def alert_allowed(kind: str) -> bool:
    """Анти-флуд: каждый тип алерта не чаще ALERT_COOLDOWN_S."""
    now = time.time()
    last = _last_alert_at.get(kind, 0)
    if now - last >= ALERT_COOLDOWN_S:
        _last_alert_at[kind] = now
        return True
    return False


async def broadcast(text: str) -> int:
    users = await execute_query("SELECT user_id FROM users", fetch=True)
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


async def send_alert(kind: str, text: str) -> None:
    """Альтернативный вход: слать алерт только если пройден коулдаун."""
    if alert_allowed(kind):
        await broadcast(text)

# --- FLASK: приём данных от станции ---
def bad_value(v: float, rng: Tuple[float, float]) -> bool:
    # Сюда попадают и NaN, и безграничные значения: сравнения с NaN дают False
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


@app.route('/health')
def health():
    """Мини-эндпоинт для ручной проверки живости: /health"""
    return "OK", 200

# --- ФОНОВЫЕ ПРОЦЕССЫ ---
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
                                   f"{round(mins_ago)} мин назад (> {SILENCE_LIMIT_MIN} мин).")
                            await broadcast(txt)
                            logger.warning("Алерт «станция молчит»: %.0f мин", mins_ago)
                    elif silence_flag:
                        silence_flag = False
                        _last_alert_at.pop('silence', None)
                        txt = "🟢 Станция вернулась в онлайн, данные снова пишутся."
                        await broadcast(txt)
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
                if stats and stats[0]:
                    uptime = str(datetime.timedelta(seconds=int(time.time() - start_time)))
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
    if TEST_MODE:
        return get_test_summary()

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
    if not rows: return "📅 Данных за сегодня еще нет."

    lines = ["📅 **Сводка за сегодня:**"]
    for row in rows:
        icon = "🌙" if row[0] == 'Ночь' else "🌅" if row[0] == 'Утро' else "☀️" if row[0] == 'День' else "🌆"
        lines.append(f"{icon} {row[0]}: {round(row[1], 1)}°C ... {round(row[2], 1)}°C")
    return "\n".join(lines)

# --- ГРАФИКИ ---
def _create_chart_sync(rows: List[Tuple], mode: str, label: str) -> Optional[io.BytesIO]:
    if not rows: return None

    plt.style.use('default')
    fig, ax = plt.subplots(figsize=(12, 6), dpi=120)

    # Тёмная "Deep Ocean"-палитра как в TestV1
    bg_color = '#0f1419'
    text_color = '#c0c8d1'
    grid_color = '#1e2734'

    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(bg_color)

    now_day = datetime.datetime.now().strftime('%d')

    if mode == 'daily':
        labels = [f"{'Сег' if r[0] == now_day else 'Вчр'} {r[1]}" for r in rows]
        data = [round(r[2], 1) for r in rows]
        line_color = '#0ea5e9'  # Мягкий небесно-голубой
    else:
        labels, data = [r[0] for r in rows], [round(r[1], 1) for r in rows]
        line_color = '#2563eb'  # Насыщенный синий

    ax.plot(labels, data, color=line_color, linewidth=3, zorder=3,
            solid_capstyle='round', solid_joinstyle='round')
    ax.fill_between(labels, min(data) - 5, data, color=line_color, alpha=0.15)

    min_val, max_val = min(data), max(data)
    min_idx = data.index(min_val)
    max_idx = data.index(max_val)

    ax.annotate(f"🔻 {min_val}°C", (labels[min_idx], min_val), xytext=(0, -15),
                textcoords="offset points", ha='center', color='#f87171', fontsize=9)
    ax.annotate(f"🔺 {max_val}°C", (labels[max_idx], max_val), xytext=(0, 10),
                textcoords="offset points", ha='center', color='#34d399', fontsize=9)

    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color(grid_color)
    ax.spines['bottom'].set_color(grid_color)

    ax.tick_params(axis='x', colors=text_color, rotation=45, labelsize=9)
    ax.tick_params(axis='y', colors=text_color, labelsize=9)

    ax.grid(True, color=grid_color, linestyle=':', linewidth=0.8, alpha=0.8)
    ax.set_axisbelow(True)

    plt.title(f"🌦 Солигорск: {label}", color=text_color, pad=15, fontsize=14, weight='bold')
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png', facecolor=bg_color)
    buf.seek(0)
    plt.close(fig)
    return buf


async def create_chart(mode: str, label: str) -> Optional[io.BytesIO]:
    if TEST_MODE:
        rows = get_test_chart_data(mode)
    else:
        if mode == 'daily':
            query = f"""
                SELECT
                    strftime('%d', datetime(timestamp, '{TIMEZONE_OFFSET}')) as d,
                    strftime('%H:00', datetime(timestamp, '{TIMEZONE_OFFSET}')) as h,
                    AVG(temp), MIN(timestamp) as ts
                FROM weather_data WHERE timestamp > datetime('now', '-24 hours')
                GROUP BY d, h ORDER BY ts ASC
            """
        elif mode == 'weekly':
            query = f"""
                SELECT strftime('%d.%m', datetime(timestamp, '{TIMEZONE_OFFSET}')) as d, AVG(temp)
                FROM weather_data WHERE timestamp > datetime('now', '-7 days')
                GROUP BY d ORDER BY MIN(timestamp) ASC
            """
        else:  # monthly
            query = f"""
                SELECT strftime('%d.%m', datetime(timestamp, '{TIMEZONE_OFFSET}')) as d, AVG(temp)
                FROM weather_data WHERE timestamp > datetime('now', '-30 days')
                GROUP BY d ORDER BY MIN(timestamp) ASC
            """
        rows = await execute_query(query, fetch=True)

    if not rows: return None

    return await asyncio.to_thread(_create_chart_sync, rows, mode, label)

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
        "👋 Метеостанция «Солигорск» (TestV2) готова!\n\n"
        "🌡 Погода сейчас • 📅 Сводка • 📊 Графики и рекорды\n"
        "Алерты: станция молчит / ошибка датчика / дайджест 21:00\n\n"
        "Домашняя станция, всё в одном флаконе :)",
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
        "ℹ️ TestV2 — что нового:\n"
        "• ключ и валидация на /update — мусор в БД не попадёт\n"
        "• алерты: «станция молчит», «ошибка датчика», дневной дайджест\n"
        "• ночные бэкапы БД, экспорт CSV, график за 30 дней\n"
        "• рекорды 24ч по температуре, влажности и давлению"
    )


@dp.message(F.text == ADMIN_PASS)
async def dev_login(message: types.Message) -> None:
    await register_user(message.from_user.id)
    await message.answer("🔓 Режим администратора.", reply_markup=get_admin_kb())


@dp.message(F.text == "Назад")
async def go_back(message: types.Message) -> None:
    await message.answer("Главное меню", reply_markup=main_kb)


@dp.message(F.text == "Погода сейчас")
async def weather_now(message: types.Message) -> None:
    await register_user(message.from_user.id)
    if TEST_MODE:
        t, h, p = get_test_current_weather()
        await message.answer(f"🌡 Температура: {t}°C\n💧 Влажность: {h}%\n☁️ Давление: {p} мм")
        return

    res = await execute_query(
        "SELECT temp, hum, pres FROM weather_data ORDER BY id DESC LIMIT 1", fetch_one=True)
    if res:
        pres = "—" if res[2] is None or str(res[2]) == 'nan' else res[2]
        await message.answer(f"🌡 Температура: {res[0]}°C\n💧 Влажность: {res[1]}%\n☁️ Давление: {pres} мм")
    else:
        await message.answer("📡 Данных нет.")


@dp.message(F.text == "Сводка за сегодня")
async def daily_summary(message: types.Message) -> None:
    await register_user(message.from_user.id)
    text = await get_daily_summary_text()
    await message.answer(text, parse_mode="Markdown")


@dp.message(F.text == "Погода за период")
async def select_period(message: types.Message) -> None:
    await message.answer("Выберите тип графика:", reply_markup=period_kb)


@dp.message(F.text == "За 24 часа")
async def chart_24h(message: types.Message) -> None:
    await register_user(message.from_user.id)
    buf = await create_chart('daily', "Температура (24ч)")
    if buf:
        await message.answer_photo(BufferedInputFile(buf.read(), "24h.png"))
    else:
        await message.answer("📉 Мало данных.")


@dp.message(F.text == "За неделю")
async def chart_7d(message: types.Message) -> None:
    await register_user(message.from_user.id)
    buf = await create_chart('weekly', "Динамика недели")
    if buf:
        await message.answer_photo(BufferedInputFile(buf.read(), "7d.png"))
    else:
        await message.answer("📉 Мало данных.")


@dp.message(F.text == "За месяц")
async def chart_30d(message: types.Message) -> None:
    await register_user(message.from_user.id)
    buf = await create_chart('monthly', "Динамика месяца")
    if buf:
        await message.answer_photo(BufferedInputFile(buf.read(), "30d.png"))
    else:
        await message.answer("📉 Мало данных.")


@dp.message(F.text == "Пределы 24ч")
async def show_limits_kb(message: types.Message) -> None:
    await message.answer("Рекорды за последние 24 часа:", reply_markup=limits_kb)

# --- РЕКОРДЫ 24Ч: общая функция по метрике ---
LIMITS = {
    "Макс °C":   ("temp", "DESC", "🔥 Максимум: `{v}°C` в `{t}`"),
    "Мин °C":    ("temp", "ASC",  "❄️ Минимум: `{v}°C` в `{t}`"),
    "Макс %":    ("hum",  "DESC", "💦 Максимум влажности: `{v}%` в `{t}`"),
    "Мин %":     ("hum",  "ASC",  "🏜 Минимум влажности: `{v}%` в `{t}`"),
    "Макс давл": ("pres", "DESC", "⬆️ Максимум давления: `{v} мм` в `{t}`"),
    "Мин давл":  ("pres", "ASC",  "⬇️ Минимум давления: `{v} мм` в `{t}`"),
}


@dp.message(F.text.in_(LIMITS.keys()))
async def show_limit(message: types.Message) -> None:
    await register_user(message.from_user.id)
    metric, order, tmpl = LIMITS[message.text]

    if TEST_MODE:
        value, ts = get_test_limit({'Макс °C': 'temp_max', 'Мин °C': 'temp_min',
                                    'Макс %': 'hum_max', 'Мин %': 'hum_min',
                                    'Макс давл': 'pres_max', 'Мин давл': 'pres_min'}[message.text])
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

# --- ХЕНДЛЕРЫ РАЗРАБОТЧИКА ---
@dp.message(F.text == "📊 Статус системы")
async def sys_status(message: types.Message) -> None:
    disk = psutil.disk_usage(DISK_PATH)
    stats = await execute_query(
        f"SELECT COUNT(*), IFNULL(datetime(MAX(timestamp), '{TIMEZONE_OFFSET}'), 'Нет') FROM weather_data",
        fetch_one=True)
    uptime = str(datetime.timedelta(seconds=int(time.time() - start_time)))
    db_size = os.path.getsize(DB_NAME) / 1024 / 1024
    backup_count = len([f for f in os.listdir(BACKUP_DIR) if f.endswith('.db')]) \
        if os.path.isdir(BACKUP_DIR) else 0
    mem = psutil.virtual_memory()
    await message.answer(
        f"🖥 **System Status (TestV2)**\n━━━━━━━━━━━━\n"
        f"📅 Последняя запись: `{stats[1]}`\n"
        f"📈 Всего записей: `{stats[0]}`\n"
        f"💾 Диск свободно: `{round(disk.free / 1024**3, 2)} GB`\n"
        f"🧠 RAM занято: `{mem.percent}%`\n"
        f"🗄 БД: `{round(db_size, 1)} MB`, бэкапов: `{backup_count}`\n"
        f"⏱ Uptime бота: `{uptime}`\n"
        f"🔇 Watchdog: `{SILENCE_LIMIT_MIN} мин`\n"
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
    lines.append(f"🧠 RAM: `{ram.percent}%` ({round(ram.used / 1024**3, 1)} из {round(ram.total / 1024**3, 1)} GB)")
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
    buf.write(("id;дата-время (UTC+3);темп °C;влажность %;давление\r\n").encode("utf-8-sig"))
    for r in rows:
        buf.write(f"{r[0]};{r[1]};{r[2]};{r[3]};{r[4]}\r\n".encode("utf-8"))
    buf.seek(0)
    await message.answer_document(
        BufferedInputFile(buf.read(), "weather_7d.csv"),
        caption=f"📦 Данные за 7 дней ({len(rows)} записей)")


@dp.message(F.text == "🕒 Последние данные")
async def last_data(message: types.Message) -> None:
    rows = await execute_query(
        f"SELECT datetime(timestamp, '{TIMEZONE_OFFSET}'), temp, hum, pres FROM weather_data ORDER BY id DESC LIMIT 5",
        fetch=True)
    if rows:
        text = "🕒 Последние 5 записей в БД:\n\n"
        for r in rows:
            pres = "—" if r[3] is None or str(r[3]) == 'nan' else r[3]
            text += f"`{r[0]}` | {r[1]}°C, {r[2]}%, {pres}мм\n"
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
    # Перед чисткой резервируем копию, чтобы чистку нельзя было откатить лишь слезами
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

# --- ЗАПУСК ---
async def main() -> None:
    logger.info("🚀 Запуск TestV2... База: %s", DB_NAME)
    init_db_sync()

    Thread(target=lambda: app.run(host='0.0.0.0', port=5001, use_reloader=False), daemon=True).start()

    def handle_signal(signum, frame):
        logger.info(f"Получен сигнал {signum}. Завершение работы...")
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    # Фоновые процессы: watchdog тишины, ошибка датчика, дайджест, бэкапы
    asyncio.create_task(silence_watcher())
    asyncio.create_task(sensor_error_watcher())
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
