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
from aiogram.fsm.filters import StateFilter

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

С вами на связи руководитель танцевальной команды Cosmos Dance Unity
https://t.me/starcosmoss

Присоединяйтесь🎉
https://vk.com/cosmos_dance_unity

Меня зовут Алёна 😊
Приглашаю вас к нам на занятия по танцам🙌

Бот используются для записи на занятия.
"""

SUB_TEXT = "💳 Абонементы уточняйте у администратора: @samorkata"

REVIEW_TEXT = """
💬 Спасибо за посещение! Будем рады отзыву 🙏
https://yandex.ru/profile/107007337379?intent=reviews
"""


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


# --- DB FUNCTIONS ---
async def get_groups_by_direction(direction):
    async with pool.acquire() as conn:
        return await conn.fetch("""
        SELECT * FROM groups
        WHERE name ILIKE $1
        ORDER BY id
        """, f"%{direction}%")


async def get_group(group_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM groups WHERE id=$1", group_id
        )


async def add_booking(data):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
        INSERT INTO bookings (user_id, fio, phone, age, style, group_id, status)
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
        return await conn.fetchrow(
            "SELECT * FROM bookings WHERE id=$1", bid
        )


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
        [InlineKeyboardButton(text="Гёрли хип-хоп", callback_data="dir_girly")],
        [InlineKeyboardButton(text="Контемпорари", callback_data="dir_contempo")],
        [InlineKeyboardButton(text="Акробатика", callback_data="dir_acro")],
        [InlineKeyboardButton(text="Фристайл", callback_data="dir_freestyle")]
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

    kb.append([
        InlineKeyboardButton(text="📝 Записаться", callback_data=f"group_{group_id}")
    ])

    return InlineKeyboardMarkup(inline_keyboard=kb)


def admin_kb(bid):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"ok_{bid}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"no_{bid}")
        ]
    ])


def admin_panel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")]
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


# --- ADMIN ---
@dp.message(Command("admin"))
async def admin_cmd(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("Введите пароль:")
    await state.set_state(AdminAuth.password)


@dp.message(AdminAuth.password)
async def check_pass(message: Message, state: FSMContext):
    if message.text == ADMIN_PASSWORD:
        await message.answer("✅ Админ-панель", reply_markup=admin_panel_kb())
    else:
        await message.answer("❌ Неверный пароль")
    await state.clear()


@dp.callback_query(F.data == "stats")
async def stats(call: CallbackQuery):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
        SELECT g.name, g.schedule, g.limit_count,
        COUNT(b.id) FILTER (WHERE b.status='approved') as used
        FROM groups g
        LEFT JOIN bookings b ON g.id=b.group_id
        GROUP BY g.id
        ORDER BY g.name
        """)

    text = "📊 Группы:\n\n"
    for r in rows:
        free = r["limit_count"] - r["used"]
        text += f"{r['name']} | {r['schedule']}\n"
        text += f"{r['used']}/{r['limit_count']} (свободно {free})\n\n"

    await call.message.answer(text)


# --- GROUPS ---
async def send_card(call, groups, index):
    if not groups:
        await call.message.answer("Нет занятий")
        return

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


@dp.message(StateFilter(BookingForm.phone))
async def phone(m: Message, s: FSMContext):
    await s.update_data(phone=m.text)
    await m.answer("Возраст:")
    await s.set_state(BookingForm.age)


@dp.message(BookingForm.phone)
async def phone(m: Message, s: FSMContext):
    await s.update_data(phone=m.text)
    await m.answer("Возраст:")
    await s.set_state(BookingForm.age)


@dp.message(StateFilter(BookingForm.age))
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
        f"""
📌 <b>Новая заявка #{bid}</b>
👤 ФИО: {data['fio']}
📞 Телефон: {data['phone']}
🎂 Возраст: {data['age']}
💃 Направление: {group['name']}
📅 Расписание: {group['schedule']}
""",
        reply_markup=admin_kb(bid),
        parse_mode="HTML"
    )

    await m.answer("Заявка отправлена 🙌")
    await s.clear()


# --- ADMIN ACTIONS ---
@dp.callback_query(F.data.startswith("ok_"))
async def ok(call: CallbackQuery):
    bid = int(call.data.split("_")[1])
    booking = await get_booking(bid)

    await update_status(bid, "approved")
    await bot.send_message(booking["user_id"], "✅ Вы записаны!")

    if "Контемпорари" in booking["style"] or "Акробатика" in booking["style"]:
        pack = "Обтягивающая одежда + носочки"
    else:
        pack = "Спортивная форма + кроссовки"

    await bot.send_message(booking["user_id"], f"📌 С собой: {pack}")
    await bot.send_message(booking["user_id"], REVIEW_TEXT)


@dp.callback_query(F.data.startswith("no_"))
async def no(call: CallbackQuery):
    bid = int(call.data.split("_")[1])
    booking = await get_booking(bid)

    await update_status(bid, "declined")
    await bot.send_message(booking["user_id"], "❌ Запись отклонена")


# --- RUN ---
async def main():
    await init_db()

    async with pool.acquire() as conn:
        await conn.execute("""
        INSERT INTO groups (name, schedule, limit_count)
        VALUES
        ('Хип-хоп дети 6-8', 'Ср 17:00-18:00', 20),
        ('Хип-хоп дети 6-8', 'Пт 17:00-18:00', 20),
        ('Хип-хоп дети 7-9', 'Пн 17:00-18:30', 20),
        ('Хип-хоп дети 7-9', 'Чт 17:00-18:30', 20),
        ('Хип-хоп дети 9-11', 'Пн 18:30-20:00', 20),
        ('Хип-хоп дети 9-11', 'Чт 18:30-20:00', 20),
        ('Хип-хоп дети 10-14', 'Ср 18:00-20:00', 20),
        ('Хип-хоп дети 10-14', 'Пт 18:00-20:00', 20),
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
