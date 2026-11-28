import asyncio
import aiosqlite
import sqlite3
import datetime
import io
import time
import os
import sys
import signal
import random
import psutil
import logging
from typing import Optional, List, Tuple
from threading import Thread
from flask import Flask, request

# Оптимизация для работы без монитора
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

# ВАЖНО: Проверь путь к диску (df -h). Если диск в /media/pi/..., поменяй путь ниже.
DISK_PATH = "/mnt/weather_data"
DB_NAME = os.path.join(DISK_PATH, "weather.db")

ADMIN_PASS = "REDACTED_OLD_ADMIN_PASS"
TIMEZONE_OFFSET = "+3 hours" # Солигорск (UTC+3)

# Глобальный флаг режима разработчика
TEST_MODE: bool = False

# Логирование
logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
logger = logging.getLogger(__name__)

# Инициализация
bot = Bot(token=TOKEN)
dp = Dispatcher()
app = Flask(__name__)
start_time = time.time()

class DevStates(StatesGroup):
    waiting_for_manual_data = State()

# --- КЛАВИАТУРЫ ---
main_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="Погода сейчас"), KeyboardButton(text="Сводка за сегодня")],
    [KeyboardButton(text="Погода за период"), KeyboardButton(text="Пределы температур")]
], resize_keyboard=True)

period_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="За 24 часа"), KeyboardButton(text="За неделю")],
    [KeyboardButton(text="Назад")]
], resize_keyboard=True)

limits_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="Максимальная °C"), KeyboardButton(text="Минимальная °C")],
    [KeyboardButton(text="Назад")]
], resize_keyboard=True)

def get_admin_kb() -> ReplyKeyboardMarkup:
    test_btn_text = "🧪 Тест без БД: ВКЛ" if TEST_MODE else "🧪 Тест без БД: ВЫКЛ"
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Статус системы"), KeyboardButton(text="📈 Аналитика")],
        [KeyboardButton(text="🌡 Темп. CPU"), KeyboardButton(text="🕒 Последние данные")],
        [KeyboardButton(text="✍️ Внести данные"), KeyboardButton(text="🧹 Очистить БД")],
        [KeyboardButton(text="🛠 Тех. перерыв"), KeyboardButton(text="✅ Возобновить")],
        [KeyboardButton(text=test_btn_text)],
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
    else:
        return [(f"{i}.11", round(random.uniform(5, 15), 1)) for i in range(1, 8)]

def get_test_limit(is_max: bool) -> Tuple[float, str]:
    temp = random.uniform(10, 25) if is_max else random.uniform(-5, 10)
    time_str = datetime.datetime.now().strftime('%H:%M')
    return (round(temp, 1), time_str)

# --- БАЗА ДАННЫХ ---
def init_db_sync() -> None:
    if not os.path.exists(DISK_PATH):
        try:
            os.makedirs(DISK_PATH)
        except Exception as e:
            logger.error(f"Не удалось создать директорию {DISK_PATH}: {e}")
            sys.exit(1)
    
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute('''CREATE TABLE IF NOT EXISTS weather_data
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                      temp REAL, hum REAL, pres REAL)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)''')
        
        # Миграция: добавяем колонку last_active для аналитики, если её нет
        try:
            conn.execute("ALTER TABLE users ADD COLUMN last_active DATETIME DEFAULT CURRENT_TIMESTAMP")
        except sqlite3.OperationalError:
            pass # Колонка уже существует
            
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

async def register_user(user_id: int) -> None:
    # Регистрируем пользователя и обновляем время последней активности (в UTC+3)
    await execute_query("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    await execute_query(f"UPDATE users SET last_active = datetime('now', '{TIMEZONE_OFFSET}') WHERE user_id = ?", (user_id,))

# --- РАССЫЛКА ---
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

# --- FLASK ---
@app.route('/update')
def update():
    try:
        t, h, p = request.args.get('t'), request.args.get('h'), request.args.get('p')
        if t and h and p:
            with sqlite3.connect(DB_NAME, timeout=10) as conn:
                conn.execute("INSERT INTO weather_data (temp, hum, pres) VALUES (?, ?, ?)", (t, h, p))
                conn.commit()
            return "OK", 200
        return "Missing args", 400
    except Exception as e:
        logger.error(f"Flask /update error: {e}")
        return str(e), 500

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
    if not rows or len(rows) < 1: return None

    plt.style.use('default')
    # Увеличили размер для лучшей читаемости
    fig, ax = plt.subplots(figsize=(12, 6), dpi=120)
    
    # Приятная глазу глубокая темная палитра (Deep Ocean)
    bg_color = '#0f1419'
    text_color = '#c0c8d1'
    grid_color = '#1e2734'
    
    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(bg_color)
    
    now_day = datetime.datetime.now().strftime('%d')

    if mode == 'daily':
        labels = [f"{'Сег' if r[0] == now_day else 'Вчр'} {r[1]}" for r in rows]
        data = [round(r[2], 1) for r in rows]
        line_color = '#0ea5e9' # Мягкий небесно-голубой
    else:
        labels, data = [r[0] for r in rows], [round(r[1], 1) for r in rows]
        line_color = '#2563eb' # Более глубокий насыщенный синий

    # Линия графика: без точек, толстая, с мягким скруглением углов
    ax.plot(labels, data, color=line_color, linewidth=3, zorder=3, 
            solid_capstyle='round', solid_joinstyle='round')
    
    # Мягкая полупрозрачная заливка под линией
    ax.fill_between(labels, min(data) - 5, data, color=line_color, alpha=0.15)

    # Автоматические маркеры для Минимума и Максимума (спокойные цвета)
    min_val = min(data)
    max_val = max(data)
    min_idx = data.index(min_val)
    max_idx = data.index(max_val)

    ax.annotate(f"🔻 {min_val}°C", (labels[min_idx], min_val), xytext=(0, -15), 
                textcoords="offset points", ha='center', color='#f87171', fontsize=9)
    ax.annotate(f"🔺 {max_val}°C", (labels[max_idx], max_val), xytext=(0, 10), 
                textcoords="offset points", ha='center', color='#34d399', fontsize=9)

    # Эстетика: убираем верхнюю и правую рамки, левую и нижнюю затемняем под фон
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color(grid_color)
    ax.spines['bottom'].set_color(grid_color)
    
    # Смягчаем цвет подписей и делаем шрифт чуть больше
    ax.tick_params(axis='x', colors=text_color, rotation=45, labelsize=9)
    ax.tick_params(axis='y', colors=text_color, labelsize=9)
    
    # Мягкая точечная сетка вместо резкого пунктира
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
        else:
            query = f"""
                SELECT strftime('%d.%m', datetime(timestamp, '{TIMEZONE_OFFSET}')) as d, AVG(temp)
                FROM weather_data WHERE timestamp > datetime('now', '-7 days')
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
    await message.answer("👋 Метеостанция готова!", reply_markup=main_kb)

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

    res = await execute_query("SELECT temp, hum, pres FROM weather_data ORDER BY id DESC LIMIT 1", fetch_one=True)
    if res:
        await message.answer(f"🌡 Температура: {res[0]}°C\n💧 Влажность: {res[1]}%\n☁️ Давление: {res[2]} мм")
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

@dp.message(F.text == "Пределы температур")
async def show_limits_kb(message: types.Message) -> None:
    await message.answer("Рекорды за последние 24 часа:", reply_markup=limits_kb)

@dp.message(F.text == "Максимальная °C")
async def max_temp(message: types.Message) -> None:
    await register_user(message.from_user.id)
    if TEST_MODE:
        temp, time_str = get_test_limit(is_max=True)
        await message.answer(f"🔥 Максимум: `{temp}°C` в `{time_str}`", parse_mode="Markdown")
        return

    res = await execute_query(f"SELECT temp, strftime('%H:%M', datetime(timestamp, '{TIMEZONE_OFFSET}')) FROM weather_data WHERE timestamp > datetime('now', '-24 hours') ORDER BY temp DESC LIMIT 1", fetch_one=True)
    if res:
        await message.answer(f"🔥 Максимум: `{res[0]}°C` в `{res[1]}`", parse_mode="Markdown")

@dp.message(F.text == "Минимальная °C")
async def min_temp(message: types.Message) -> None:
    await register_user(message.from_user.id)
    if TEST_MODE:
        temp, time_str = get_test_limit(is_max=False)
        await message.answer(f"❄️ Минимум: `{temp}°C` в `{time_str}`", parse_mode="Markdown")
        return

    res = await execute_query(f"SELECT temp, strftime('%H:%M', datetime(timestamp, '{TIMEZONE_OFFSET}')) FROM weather_data WHERE timestamp > datetime('now', '-24 hours') ORDER BY temp ASC LIMIT 1", fetch_one=True)
    if res:
        await message.answer(f"❄️ Минимум: `{res[0]}°C` в `{res[1]}`", parse_mode="Markdown")

# --- ХЕНДЛЕРЫ РАЗРАБОТЧИКА ---
@dp.message(F.text == "📊 Статус системы")
async def sys_status(message: types.Message) -> None:
    disk = psutil.disk_usage(DISK_PATH)
    stats = await execute_query(f"SELECT COUNT(*), IFNULL(datetime(MAX(timestamp), '{TIMEZONE_OFFSET}'), 'Нет') FROM weather_data", fetch_one=True)
    uptime = str(datetime.timedelta(seconds=int(time.time() - start_time)))
    await message.answer(f"🖥 **System Status**\n━━━━━━━━━━━━\n📅 Запись: `{stats[1]}`\n📈 Всего: `{stats[0]}`\n💾 Свободно: `{round(disk.free / 1024**3, 2)} GB`\n⏱ Uptime: `{uptime}`\n🧪 Test Mode: `{'ВКЛ' if TEST_MODE else 'ВЫКЛ'}`", parse_mode="Markdown")

@dp.message(F.text == "📈 Аналитика")
async def analytics(message: types.Message) -> None:
    # Считаем уникальных пользователей, активных за последний час
    active_1h = await execute_query(f"SELECT COUNT(*) FROM users WHERE last_active > datetime('now', '{TIMEZONE_OFFSET}', '-1 hour')", fetch_one=True)
    # Считаем общее количество пользователей
    total_users = await execute_query("SELECT COUNT(*) FROM users", fetch_one=True)
    # Считаем, сколько раз датчики отправили данные за последний час
    sensor_1h = await execute_query("SELECT COUNT(*) FROM weather_data WHERE timestamp > datetime('now', '-1 hour')", fetch_one=True)
    
    await message.answer(
        f"📈 **Аналитика бота:**\n"
        f"━━━━━━━━━━━━\n"
        f"👥 Всего пользователей: `{total_users[0] if total_users else 0}`\n"
        f"⏱ Активны за 1 час: `{active_1h[0] if active_1h else 0}`\n"
        f"📡 Запросов от датчиков за 1 час: `{sensor_1h[0] if sensor_1h else 0}`\n",
        parse_mode="Markdown"
    )

@dp.message(F.text == "🌡 Темп. CPU")
async def cpu_temp(message: types.Message) -> None:
    try:
        # Стандартный путь для одноплаток на базе Linux (ARM)
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            temp_raw = f.read().strip()
        temp_cpu = round(int(temp_raw) / 1000.0, 1)
        
        if temp_cpu < 50:
            status = "❄️ Норма"
        elif temp_cpu < 70:
            status = "🟡 Тепло"
        else:
            status = "🔴 Опасно!"
            
        await message.answer(f"🌡 Температура процессора: `{temp_cpu}°C`\nСтатус: {status}", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка чтения температуры CPU: {e}")
        await message.answer("❌ Не удалось получить температуру процессора. (Возможно, путь к датчику отличается)")

@dp.message(F.text == "🕒 Последние данные")
async def last_data(message: types.Message) -> None:
    rows = await execute_query(f"SELECT datetime(timestamp, '{TIMEZONE_OFFSET}'), temp, hum, pres FROM weather_data ORDER BY id DESC LIMIT 5", fetch=True)
    if rows:
        text = "🕒 Последние 5 записей в БД:\n\n"
        for r in rows:
            text += f"`{r[0]}` | {r[1]}°C, {r[2]}%, {r[3]}мм\n"
        await message.answer(text, parse_mode="Markdown")
    else:
        await message.answer("База данных пуста.")

@dp.message(F.text == "✍️ Внести данные")
async def manual_insert_start(message: types.Message, state: FSMContext) -> None:
    await message.answer("✍️ Отправьте данные в формате: `Темп Влажность Давление`\nНапример: `25.5 60 745`\n\nДля отмены напишите 'Отмена'.", parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
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
        
        t, h, p = parts
        float(t), int(h), int(p) # Валидация типов
        
        await execute_query("INSERT INTO weather_data (temp, hum, pres) VALUES (?, ?, ?)", (t, h, p))
        await state.clear()
        await message.answer(f"✅ Данные `{t}°C, {h}%, {p}мм` успешно добавлены в БД!", parse_mode="Markdown", reply_markup=get_admin_kb())
    except Exception as e:
        await message.answer(f"❌ Ошибка формата: `{e}`. Попробуй еще раз или напиши 'Отмена'.", parse_mode="Markdown")

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
    await execute_query("DELETE FROM weather_data")
    await message.answer("🗑 База очищена.")

@dp.message(F.text.in_({"🧪 Тест без БД: ВЫКЛ", "🧪 Тест без БД: ВКЛ"}))
async def toggle_test_mode(message: types.Message) -> None:
    global TEST_MODE
    TEST_MODE = not TEST_MODE
    await message.answer(f"🧪 Тестовый режим {'ВКЛЮЧЕН' if TEST_MODE else 'ВЫКЛЮЧЕН'}.", reply_markup=get_admin_kb())

@dp.message(F.text == "🚪 Выход")
async def exit_admin(message: types.Message) -> None:
    await message.answer("Выход в главное меню", reply_markup=main_kb)

# --- ЗАПУСК ---
async def main() -> None:
    logger.info(f"🚀 Запуск... База: {DB_NAME}")
    init_db_sync()
    
    Thread(target=lambda: app.run(host='0.0.0.0', port=5000, use_reloader=False), daemon=True).start()
    
    def handle_signal(signum, frame):
        logger.info(f"Получен сигнал {signum}. Завершение работы...")
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен вручную.")
    except Exception as e:
        logger.exception(f"Критическая ошибка: {e}")