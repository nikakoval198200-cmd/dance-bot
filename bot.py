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


# --- DB ---
async def get_group(group_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM groups WHERE id=$1", group_id)


async def get_groups():
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM groups")


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


async def count_in_group(group_id):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
        SELECT COUNT(*) FROM bookings
        WHERE group_id=$1 AND status='approved'
        """, group_id)
        return row["count"]


# --- KEYBOARDS ---
def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📦 Группы", callback_data="admin_groups")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_refresh")]
    ])


# --- START ---
@dp.message(CommandStart())
async def start(message: Message):
    await message.answer("Добрый день 🙌")


# --- ADMIN ENTRY ---
@dp.message(F.text == "/admin")
async def admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("🧑‍💼 Админ-панель", reply_markup=admin_menu())


# --- ADMIN STATS ---
@dp.callback_query(F.data == "admin_stats")
async def admin_stats(call: CallbackQuery):
    groups = await get_groups()

    text = "📊 ЗАГРУЗКА ГРУПП:\n\n"

    for g in groups:
        busy = await count_in_group(g["id"])
        free = g["limit_count"] - busy

        text += (
            f"🟣 {g['name']}\n"
            f"📅 {g['schedule']}\n"
            f"👥 {busy}/{g['limit_count']} (свободно {free})\n\n"
        )

    await call.message.edit_text(text, reply_markup=admin_menu())


# --- GROUP LIST ---
@dp.callback_query(F.data == "admin_groups")
async def admin_groups(call: CallbackQuery):
    groups = await get_groups()

    text = "📦 СПИСОК ГРУПП:\n\n"
    for g in groups:
        text += f"• {g['name']} — {g['schedule']}\n"

    await call.message.edit_text(text, reply_markup=admin_menu())


# --- REFRESH ---
@dp.callback_query(F.data == "admin_refresh")
async def refresh(call: CallbackQuery):
    await admin_stats(call)


# --- RUN ---
async def main():
    await init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
