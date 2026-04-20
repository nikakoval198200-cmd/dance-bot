import asyncio
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

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
MSK = ZoneInfo("Europe/Moscow")

REVIEW_LINK = "https://yandex.ru/profile/107007337379?intent=reviews"


# --- FSM ---
class BookingForm(StatesGroup):
    fio = State()
    phone = State()
    age = State()


# --- INIT DB ---
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

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id SERIAL PRIMARY KEY,
            booking_id INT,
            remind_24h BOOLEAN DEFAULT FALSE,
            remind_2h BOOLEAN DEFAULT FALSE,
            review_sent BOOLEAN DEFAULT FALSE,
            event_time TIMESTAMP
        );
        """)

        await conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS groups_unique
        ON groups(name, schedule);
        """)


# --- HELP: PARSE SCHEDULE ---
def parse_schedule(schedule_text: str):
    """
    Пример:
    'Пн 17:00-18:00'
    """
    days_map = {
        "Пн": 0,
        "Вт": 1,
        "Ср": 2,
        "Чт": 3,
        "Пт": 4,
        "Сб": 5,
        "Вс": 6
    }

    day, time = schedule_text.split()
    start_time = time.split("-")[0]

    hour, minute = map(int, start_time.split(":"))

    return days_map[day], hour, minute


def get_next_event_datetime(day, hour, minute):
    now = datetime.now(MSK)

    days_ahead = (day - now.weekday() + 7) % 7
    if days_ahead == 0 and now.hour > hour:
        days_ahead = 7

    event = now + timedelta(days=days_ahead)
    return event.replace(hour=hour, minute=minute, second=0, microsecond=0)


# --- DB ---
async def get_group(group_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM groups WHERE id=$1", group_id)


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
            status, bid
        )


async def get_booking(bid):
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM bookings WHERE id=$1", bid)


# --- KEYBOARDS ---
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Записаться", callback_data="start")]
    ])


# --- START ---
@dp.message(CommandStart())
async def start(message: Message):
    await message.answer("Добрый день 🙌", reply_markup=main_menu())


# --- BOOKING FINISH ---
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

    await bot.send_message(ADMIN_ID, f"Новая заявка #{bid}")

    await message.answer("Заявка отправлена 🙌")
    await state.clear()


# --- APPROVE ---
@dp.callback_query(F.data.startswith("ok_"))
async def approve(call: CallbackQuery):
    bid = int(call.data.split("_")[1])
    booking = await get_booking(bid)
    group = await get_group(booking["group_id"])

    await update_status(bid, "approved")

    day, hour, minute = parse_schedule(group["schedule"])
    event_time = get_next_event_datetime(day, hour, minute)

    # экипировка
    if "Контемпорари" in group["name"] or "Акробатика" in group["name"]:
        gear = "Обтягивающая одежда и носочки"
    else:
        gear = "Спортивная одежда и кроссовки"

    await bot.send_message(
        booking["user_id"],
        f"""✅ Вы записаны!

🎒 Что взять:
{gear}

⏰ Напоминания будут автоматически перед занятием
"""
    )

    async with pool.acquire() as conn:
        await conn.execute("""
        INSERT INTO reminders (booking_id, event_time)
        VALUES ($1,$2)
        """, bid, event_time)

    await call.answer()


# --- BACKGROUND TASK (IDEAL REMINDERS) ---
async def reminder_worker():
    while True:
        now = datetime.now(MSK)

        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT r.*, b.user_id
                FROM reminders r
                JOIN bookings b ON b.id = r.booking_id
            """)

        for r in rows:
            event = r["event_time"]

            # 24h
            if not r["remind_24h"] and now >= event - timedelta(hours=24):
                await bot.send_message(r["user_id"], "⏰ Завтра занятие!")
                await pool.execute("UPDATE reminders SET remind_24h=TRUE WHERE id=$1", r["id"])

            # 2h
            if not r["remind_2h"] and now >= event - timedelta(hours=2):
                await bot.send_message(r["user_id"], "⏰ Через 2 часа занятие!")
                await pool.execute("UPDATE reminders SET remind_2h=TRUE WHERE id=$1", r["id"])

            # review
            if not r["review_sent"] and now >= event + timedelta(hours=1):
                await bot.send_message(
                    r["user_id"],
                    f"⭐ Спасибо за занятие! Оставьте отзыв: {REVIEW_LINK}"
                )
                await pool.execute("UPDATE reminders SET review_sent=TRUE WHERE id=$1", r["id"])

        await asyncio.sleep(60)


# --- RUN ---
async def main():
    await init_db()
    asyncio.create_task(reminder_worker())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
