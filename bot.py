import asyncio
import os
from zoneinfo import ZoneInfo

import asyncpg
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- CONFIG ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_PASSWORD = "0602"

bot = Bot(TOKEN)
dp = Dispatcher(storage=MemoryStorage())

pool = None
MSK = ZoneInfo("Europe/Moscow")

user_cache = {}

# --- FSM ---
class BookingForm(StatesGroup):
    fio = State()
    phone = State()
    age = State()

class AdminAuth(StatesGroup):
    password = State()

# --- TEXTS ---
WELCOME_TEXT = """
Добрый день🙌
С вами Cosmos Dance Unity

Выберите действие👇
"""

SUB_TEXT = "💳 Абонементы уточняйте у администратора" samorkata."

# --- DB INIT ---
async def init_db():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)

    async with pool.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            id SERIAL PRIMARY KEY,
            name TEXT,
            schedule TEXT,
            limit_count INT,
            UNIQUE(name, schedule)
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

# --- DB ---
async def get_groups_by_direction(direction):
    async with pool.acquire() as conn:
        return await conn.fetch("""
        SELECT * FROM groups
        WHERE name ILIKE $1
        ORDER BY id
        """, f"%{direction}%")

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
        data["user_id"], data["fio"], data["phone"],
        data["age"], data["style"], data["group_id"])

        return row["id"]

async def count_in_group(group_id):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
        SELECT COUNT(*) FROM bookings
        WHERE group_id=$1 AND status='approved'
        """, group_id)
        return int(row["count"])

# --- KEYBOARDS ---
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Записаться", callback_data="start")],
        [InlineKeyboardButton(text="💳 Абонементы", callback_data="subs")]
    ])

def directions_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Хип-хоп дети", callback_data="dir_kids")],
        [InlineKeyboardButton(text="Хип-хоп взрослые", callback_data="dir_adult")],
        [InlineKeyboardButton(text="Гёрли", callback_data="dir_girly")],
        [InlineKeyboardButton(text="Контемпорари", callback_data="dir_contempo")],
        [InlineKeyboardButton(text="Акробатика", callback_data="dir_acro")],
        [InlineKeyboardButton(text="Фристайл", callback_data="dir_freestyle")],
    ])

def card_kb(group_id, index, total):
    nav = []
    if index > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"nav_{index-1}"))
    if index < total - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"nav_{index+1}"))

    kb = []
    if nav:
        kb.append(nav)

    kb.append([InlineKeyboardButton(text="📝 Записаться", callback_data=f"group_{group_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def admin_kb(bid):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅", callback_data=f"ok_{bid}"),
            InlineKeyboardButton(text="❌", callback_data=f"no_{bid}")
        ]
    ])

# --- START ---
@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(WELCOME_TEXT, reply_markup=main_menu())

@dp.callback_query(F.data == "subs")
async def subs(call: CallbackQuery):
    await call.message.answer(SUB_TEXT)

@dp.callback_query(F.data == "start")
async def choose(call: CallbackQuery):
    await call.message.answer("Выберите направление:", reply_markup=directions_kb())

# --- ADMIN LOGIN ---
@dp.message(Command("admin"))
async def admin_cmd(message: Message, state: FSMContext):
    await message.answer("Введите пароль:")
    await state.set_state(AdminAuth.password)

@dp.message(AdminAuth.password)
async def check_pass(message: Message, state: FSMContext):
    if message.text == ADMIN_PASSWORD:
        await message.answer("✅ Доступ открыт")
        await message.answer("📊 Используй кнопки заявок")
    else:
        await message.answer("❌ Неверный пароль")
    await state.clear()

# --- GROUPS ---
async def send_card(call, groups, index):
    g = groups[index]
    busy = await count_in_group(g["id"])
    free = g["limit_count"] - busy

    text = f"""
🟣 <b>{g['name']}</b>

📅 {g['schedule']}
👥 Свободно: {free}
"""

    await call.message.edit_text(
        text,
        reply_markup=card_kb(g["id"], index, len(groups)),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("dir_"))
async def show(call: CallbackQuery):
    mapping = {
        "dir_kids": "Хип-хоп дети",
        "dir_adult": "Хип-хоп взрослые",
        "dir_girly": "Гёрли",
        "dir_contempo": "Контемпорари",
        "dir_acro": "Акробатика",
        "dir_freestyle": "Фристайл"
    }

    groups = await get_groups_by_direction(mapping[call.data])
    user_cache[call.from_user.id] = groups
    await send_card(call, groups, 0)

@dp.callback_query(F.data.startswith("nav_"))
async def nav(call: CallbackQuery):
    idx = int(call.data.split("_")[1])
    groups = user_cache.get(call.from_user.id, [])
    await send_card(call, groups, idx)

# --- BOOKING ---
@dp.callback_query(F.data.startswith("group_"))
async def select(call: CallbackQuery, state: FSMContext):
    await state.update_data(group_id=int(call.data.split("_")[1]))
    await call.message.answer("ФИО:")
    await state.set_state(BookingForm.fio)

@dp.message(BookingForm.fio)
async def fio(m: Message, s: FSMContext):
    await s.update_data(fio=m.text)
    await m.answer("Телефон:")
    await s.set_state(BookingForm.phone)

@dp.message(BookingForm.phone)
async def phone(m: Message, s: FSMContext):
    await s.update_data(phone=m.text)
    await m.answer("Возраст:")
    await s.set_state(BookingForm.age)

@dp.message(BookingForm.age)
async def finish(m: Message, s: FSMContext):
    data = await s.get_data()
    group = await get_group(data["group_id"])

    data.update({
        "age": m.text,
        "style": group["name"],
        "user_id": m.from_user.id
    })

    bid = await add_booking(data)

    await bot.send_message(
        ADMIN_ID,
        f"Заявка #{bid}\n{data['fio']}\n{group['name']}",
        reply_markup=admin_kb(bid)
    )

    await m.answer("Заявка отправлена 🙌")
    await s.clear()

# --- ADMIN ACTIONS ---
@dp.callback_query(F.data.startswith("ok_"))
async def ok(call: CallbackQuery):
    bid = int(call.data.split("_")[1])
    await bot.send_message(call.from_user.id, f"Заявка {bid} одобрена")

@dp.callback_query(F.data.startswith("no_"))
async def no(call: CallbackQuery):
    bid = int(call.data.split("_")[1])
    await bot.send_message(call.from_user.id, f"Заявка {bid} отклонена")

# --- RUN ---
async def main():
    await init_db()

    async with pool.acquire() as conn:
        await conn.execute("""
        INSERT INTO groups (name, schedule, limit_count) VALUES
        ('Хип-хоп дети 6-8', 'Ср, Пт 17:00-18:00', 20),
        ('Хип-хоп дети 7-9', 'Пн, Чт 17:00-18:30', 20),
        ('Хип-хоп дети 9-11', 'Пн, Чт 18:30-20:00', 20),
        ('Хип-хоп дети 10-14', 'Ср, Пт 18:00-20:00', 20),

        ('Хип-хоп взрослые', 'Ср 17:00-18:00', 20),
        ('Хип-хоп взрослые', 'Пт 19:00-20:00', 20),

        ('Контемпорари', 'Вт 20:00-21:00', 20),
        ('Контемпорари', 'Сб 11:00-12:00', 20),

        ('Гёрли хип-хоп', 'Пн 19:00-20:00', 20),
        ('Гёрли хип-хоп', 'Чт 20:00-21:00', 20),

        ('Акробатика 5-7', 'Сб 10:45-11:45', 20),
        ('Акробатика 7-12', 'Сб 12:00-13:00', 20),

        ('Фристайл', 'Пт 16:00-17:00', 20)

        ON CONFLICT DO NOTHING;
        """)

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
