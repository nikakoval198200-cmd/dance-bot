import asyncio
import os
from datetime import datetime, timedelta
import pytz

import asyncpg
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


# --- CONFIG ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
DATABASE_URL = os.getenv("DATABASE_URL")

bot = Bot(TOKEN)
dp = Dispatcher(storage=MemoryStorage())

pool = None
MSK = pytz.timezone("Europe/Moscow")


# --- FSM ---
class BookingForm(StatesGroup):
    fio = State()
    phone = State()
    age = State()


# --- DB ---
async def init_db():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)

    async with pool.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            id SERIAL PRIMARY KEY,
            name TEXT,
            schedule TEXT,
            limit_count INT
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            fio TEXT,
            phone TEXT,
            age TEXT,
            style TEXT,
            group_id INT,
            status TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)


# --- HELPERS ---
def parse_datetime(schedule: str):
    # "Ср 17:00-18:00"
    days = {
        "Пн": 0, "Вт": 1, "Ср": 2,
        "Чт": 3, "Пт": 4, "Сб": 5, "Вс": 6
    }

    day, time = schedule.split()
    hour, minute = map(int, time.split("-")[0].split(":"))

    now = datetime.now(MSK)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    days_ahead = (days[day] - now.weekday()) % 7
    target += timedelta(days=days_ahead)

    return target


async def count_active(group_id, schedule):
    lesson_time = parse_datetime(schedule)

    if lesson_time < datetime.now(MSK):
        return 0

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
        SELECT COUNT(*) FROM bookings
        WHERE group_id=$1 AND status='approved'
        """, group_id)

        return row["count"]


# --- DB ---
async def get_groups_by_direction(direction):
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM groups WHERE name ILIKE $1",
            f"%{direction}%"
        )


async def get_group(group_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM groups WHERE id=$1",
            group_id
        )


async def add_booking(data):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
        INSERT INTO bookings
        (user_id, fio, phone, age, style, group_id, status)
        VALUES ($1,$2,$3,$4,$5,$6,'pending')
        RETURNING id
        """,
        data["user_id"],
        data["fio"],
        data["phone"],
        data["age"],
        data["style"],
        data["group_id"])

        return row["id"]


async def update_status(bid, status):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE bookings SET status=$1 WHERE id=$2",
            status,
            bid
        )


async def get_booking(bid):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM bookings WHERE id=$1",
            bid
        )


# --- UI ---
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Записаться", callback_data="start")]
    ])


def directions_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Хип-хоп дети", callback_data="dir_kids")],
        [InlineKeyboardButton(text="Хип-хоп взрослые", callback_data="dir_adult")],
        [InlineKeyboardButton(text="Гёрли", callback_data="dir_girly")],
        [InlineKeyboardButton(text="Контемпорари", callback_data="dir_contempo")],
        [InlineKeyboardButton(text="Акробатика", callback_data="dir_acro")],
        [InlineKeyboardButton(text="Фристайл", callback_data="dir_freestyle")]
    ])


def card_kb(group_id, index, total):
    buttons = []

    nav = []
    if index > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"nav_{index-1}"))
    if index < total - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"nav_{index+1}"))

    if nav:
        buttons.append(nav)

    buttons.append([
        InlineKeyboardButton(text="📝 Записаться", callback_data=f"group_{group_id}")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# --- START ---
@dp.message(CommandStart())
async def start(message: Message):
    await message.answer("Выберите направление", reply_markup=directions_kb())


# --- NAVIGATION STATE ---
user_cache = {}


# --- SHOW GROUP ---
async def send_card(call, groups, index):
    g = groups[index]

    busy = await count_active(g["id"], g["schedule"])
    free = g["limit_count"] - busy

    text = f"""
🟣 <b>{g['name']}</b>

📅 {g['schedule']}
🟢 Свободных мест: {free}
"""

    await call.message.edit_text(
        text,
        reply_markup=card_kb(g["id"], index, len(groups)),
        parse_mode="HTML"
    )


@dp.callback_query(F.data.startswith("dir_"))
async def show_groups(call: CallbackQuery):
    mapping = {
        "dir_kids": "Хип-хоп дети",
        "dir_adult": "Хип-хоп взрослые",
        "dir_girly": "Гёрли",
        "dir_contempo": "Контемпорари",
        "dir_acro": "Акробатика",
        "dir_freestyle": "Фристайл"
    }

    direction = mapping[call.data]
    groups = await get_groups_by_direction(direction)

    user_cache[call.from_user.id] = groups

    await send_card(call, groups, 0)


@dp.callback_query(F.data.startswith("nav_"))
async def navigate(call: CallbackQuery):
    index = int(call.data.split("_")[1])
    groups = user_cache.get(call.from_user.id)

    await send_card(call, groups, index)


# --- BOOKING FLOW ---
@dp.callback_query(F.data.startswith("group_"))
async def select_group(call: CallbackQuery, state: FSMContext):
    gid = int(call.data.split("_")[1])
    await state.update_data(group_id=gid)

    await call.message.answer("Введите ФИО:")
    await state.set_state(BookingForm.fio)


@dp.message(BookingForm.fio)
async def fio(message: Message, state: FSMContext):
    await state.update_data(fio=message.text)
    await message.answer("Телефон:")
    await state.set_state(BookingForm.phone)


@dp.message(BookingForm.phone)
async def phone(message: Message, state: FSMContext):
    await state.update_data(phone=message.text)
    await message.answer("Возраст:")
    await state.set_state(BookingForm.age)


@dp.message(BookingForm.age)
async def finish(message: Message, state: FSMContext):
    data = await state.get_data()
    group = await get_group(data["group_id"])

    data.update({
        "age": message.text,
        "style": group["name"],
        "user_id": message.from_user.id
    })

    bid = await add_booking(data)

    text = f"""
Заявка #{bid}

ФИО: {data['fio']}
Телефон: {data['phone']}
Возраст: {data['age']}

Направление: {group['name']}
Расписание: {group['schedule']}

Username: @{message.from_user.username}
"""

    await bot.send_message(ADMIN_ID, text)

    await message.answer("Заявка отправлена 🙌")
    await state.clear()


# --- REMINDER ---
async def reminder_loop():
    while True:
        async with pool.acquire() as conn:
            bookings = await conn.fetch("""
            SELECT b.*, g.schedule FROM bookings b
            JOIN groups g ON g.id=b.group_id
            WHERE status='approved'
            """)

        now = datetime.now(MSK)

        for b in bookings:
            lesson = parse_datetime(b["schedule"])
            if 0 < (lesson - now).total_seconds() < 7200:
                await bot.send_message(
                    b["user_id"],
                    f"⏰ Напоминание! Сегодня занятие:\n{b['schedule']}"
                )

        await asyncio.sleep(1800)


# --- RUN ---
async def main():
    await init_db()

    asyncio.create_task(reminder_loop())

    async with pool.acquire() as conn:
        await conn.execute("""
        INSERT INTO groups (name, schedule, limit_count) VALUES
        ('Хип-хоп дети 6-8', 'Ср 17:00-18:00', 20),
        ('Хип-хоп дети 7-9', 'Пн 17:00-18:30', 20),
        ('Хип-хоп взрослые', 'Ср 17:00-18:00', 20),
        ('Гёрли хип-хоп', 'Пн 19:00-20:00', 20),
        ('Контемпорари', 'Вт 20:00-21:00', 20),
        ('Акробатика', 'Сб 12:00-13:00', 20),
        ('Фристайл', 'Пт 16:00-17:00', 20)
        ON CONFLICT DO NOTHING;
        """)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
