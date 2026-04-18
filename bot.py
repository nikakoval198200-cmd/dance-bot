import asyncio
import os
import aiosqlite

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


# --- CONFIG ---
TOKEN = "8715454752:AAHkMyw_E_pSdSjmHI605KCdWnGhtG5cnlg"
ADMIN_ID =  5420031708

bot = Bot(TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# --- FSM ---
class BookingForm(StatesGroup):
    fio = State()
    phone = State()
    age = State()


# --- DB ---
DB_NAME = "dance.db"


async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY,
            name TEXT,
            schedule TEXT,
            limit_count INTEGER
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            fio TEXT,
            phone TEXT,
            age TEXT,
            style TEXT,
            group_id INTEGER,
            status TEXT
        )
        """)

        await db.commit()


async def get_groups():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT * FROM groups")
        return await cursor.fetchall()


async def get_group(group_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT * FROM groups WHERE id = ?", (group_id,))
        return await cursor.fetchone()


async def count_in_group(group_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM bookings WHERE group_id = ? AND status = 'approved'",
            (group_id,)
        )
        result = await cursor.fetchone()
        return result[0]


async def add_booking(data):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("""
        INSERT INTO bookings (user_id, fio, phone, age, style, group_id, status)
        VALUES (?, ?, ?, ?, ?, ?, 'pending')
        """, (
            data["user_id"],
            data["fio"],
            data["phone"],
            data["age"],
            data["style"],
            data["group_id"]
        ))
        await db.commit()
        return cursor.lastrowid


async def get_booking(booking_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,))
        return await cursor.fetchone()


async def update_status(booking_id, status):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE bookings SET status = ? WHERE id = ?",
            (status, booking_id)
        )
        await db.commit()


# --- KEYBOARDS ---
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Записаться", callback_data="start")],
        [InlineKeyboardButton(text="💳 Абонементы", callback_data="abon")]
    ])


def groups_kb(groups):
    kb = []
    for g in groups:
        text = f"{g[1]} | {g[2]}"
        kb.append([InlineKeyboardButton(text=text, callback_data=f"group_{g[0]}")])
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def back():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")]
    ])


def admin_kb(booking_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"ok_{booking_id}"),
            InlineKeyboardButton(text="❌ Отказать", callback_data=f"no_{booking_id}")
        ]
    ])


# --- START ---
@dp.message(CommandStart())
async def start(message: Message):
    text = """Добрый день🙌
Я Алёна, руководитель Cosmos Dance Unity 💫

Выберите действие👇"""
    await message.answer(text, reply_markup=main_menu())


# --- АБОНЕМЕНТ ---
@dp.callback_query(F.data == "abon")
async def abon(call: CallbackQuery):
    await call.message.delete()
    await call.message.answer(
        "Напишите для покупки 👉 @samorkata",
        reply_markup=back()
    )


# --- НАЗАД ---
@dp.callback_query(F.data == "back_main")
async def back_main(call: CallbackQuery):
    await call.message.delete()
    await call.message.answer("Главное меню", reply_markup=main_menu())


# --- ГРУППЫ ---
@dp.callback_query(F.data == "start")
async def choose_group(call: CallbackQuery):
    await call.message.delete()
    groups = await get_groups()
    await call.message.answer("Выберите группу:", reply_markup=groups_kb(groups))


# --- ВЫБОР ГРУППЫ ---
@dp.callback_query(F.data.startswith("group_"))
async def select_group(call: CallbackQuery, state: FSMContext):
    group_id = int(call.data.split("_")[1])

    count = await count_in_group(group_id)
    group = await get_group(group_id)

    if count >= group[3]:
        await call.message.answer("❌ Группа заполнена")
        return

    await state.update_data(group_id=group_id)
    await call.message.delete()
    await call.message.answer("Введите ФИО:")
    await state.set_state(BookingForm.fio)


# --- АНКЕТА ---
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
async def age(message: Message, state: FSMContext):
    data = await state.get_data()

    group = await get_group(data["group_id"])

    data.update({
        "age": message.text,
        "style": group[1],
        "user_id": message.from_user.id
    })

    booking_id = await add_booking(data)

    text = f"""
Заявка #{booking_id}

ФИО: {data['fio']}
Телефон: {data['phone']}
Возраст: {data['age']}
Группа: {data['style']}
Username: @{message.from_user.username}
"""

    await bot.send_message(ADMIN_ID, text, reply_markup=admin_kb(booking_id))

    await message.answer("Спасибо за заявку 🙌 Ожидайте подтверждения")

    await state.clear()


# --- ПОДТВЕРЖДЕНИЕ ---
@dp.callback_query(F.data.startswith("ok_"))
async def approve(call: CallbackQuery):
    booking_id = int(call.data.split("_")[1])

    booking = await get_booking(booking_id)

    await update_status(booking_id, "approved")

    await bot.send_message(booking[1], "✅ Вы записаны!")
    await call.answer("Подтверждено")


# --- ОТКАЗ ---
@dp.callback_query(F.data.startswith("no_"))
async def decline(call: CallbackQuery):
    booking_id = int(call.data.split("_")[1])

    booking = await get_booking(booking_id)

    await update_status(booking_id, "declined")

    await bot.send_message(booking[1], "❌ Запись отклонена")
    await call.answer("Отклонено")


# --- RUN ---
async def main():
    await init_db()

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        INSERT OR IGNORE INTO groups (id, name, schedule, limit_count)
        VALUES 
        (1, 'Хип-хоп дети 6-8', 'Ср Пт 17:00-18:00', 20),
        (2, 'Хип-хоп дети 7-9', 'Пн Чт 17:00-18:30', 20),
        (3, 'Хип-хоп дети 9-11', 'Пн Чт 18:30-20:00', 20),
        (4, 'Хип-хоп дети 10-14', 'Ср Пт 18:00-20:00', 20),

        (5, 'Хип-хоп взрослые', 'Ср 17:00-18:00', 20),
        (6, 'Хип-хоп взрослые', 'Пт 19:00-20:00', 20),

        (7, 'Контемпорари 7-12', 'Вт 20:00-21:00', 20),
        (8, 'Контемпорари 7-12', 'Сб 11:00-12:00', 20),

        (9, 'Гёрли хип-хоп', 'Пн 19:00-20:00', 20),
        (10, 'Гёрли хип-хоп', 'Чт 20:00-21:00', 20),

        (11, 'Акробатика 5-7', 'Сб 10:45-11:45', 20),
        (12, 'Акробатика 7-12', 'Сб 12:00-13:00', 20),

        (13, 'Фристайл 6+', 'Пт 16:00-17:00', 20)
        """)
        await db.commit()

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
