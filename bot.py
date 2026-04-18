import asyncio
import aiosqlite
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


# --- CONFIG ---
TOKEN = "8715454752:AAHkMyw_E_pSdSjmHI605KCdWnGhtG5cnlg"
ADMIN_ID = 5420031708

bot = Bot(TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# --- FSM ---
class BookingForm(StatesGroup):
    fio = State()
    phone = State()
    age = State()


# --- DB ---
DB_NAME = "dance.db"


# --- ДНИ НЕДЕЛИ ---
WEEKDAYS = {
    "Пн": 0, "Вт": 1, "Ср": 2,
    "Чт": 3, "Пт": 4, "Сб": 5, "Вс": 6
}


# --- INIT DB ---
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

        await db.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            booking_id INTEGER,
            last_sent TEXT
        )
        """)

        await db.commit()


# --- DB FUNCTIONS ---
async def get_groups_by_direction(direction):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT * FROM groups WHERE name LIKE ?",
            (f"%{direction}%",)
        )
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
        return (await cursor.fetchone())[0]


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
        await db.execute("UPDATE bookings SET status = ? WHERE id = ?", (status, booking_id))
        await db.commit()


# --- ПАРСИНГ ВРЕМЕНИ ---
def get_next_lesson_datetime(schedule: str):
    day, time_range = schedule.split()
    start_time = time_range.split("-")[0]

    hour, minute = map(int, start_time.split(":"))

    now = datetime.now()
    target_day = WEEKDAYS[day]

    days_ahead = target_day - now.weekday()
    if days_ahead <= 0:
        days_ahead += 7

    lesson = now + timedelta(days=days_ahead)
    return lesson.replace(hour=hour, minute=minute, second=0, microsecond=0)


# --- НАПОМИНАНИЯ ---
async def reminder_worker():
    while True:
        now = datetime.now()

        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute("""
            SELECT b.id, b.user_id, g.name, g.schedule
            FROM bookings b
            JOIN groups g ON b.group_id = g.id
            WHERE b.status = 'approved'
            """)
            rows = await cursor.fetchall()

            for booking_id, user_id, name, schedule in rows:
                lesson_time = get_next_lesson_datetime(schedule)
                diff = (lesson_time - now).total_seconds()

                if 3540 < diff < 3660:
                    cur2 = await db.execute(
                        "SELECT * FROM reminders WHERE booking_id = ?",
                        (booking_id,)
                    )
                    if await cur2.fetchone():
                        continue

                    try:
                        await bot.send_message(
                            user_id,
                            f"⏰ Напоминание!\n\nСегодня занятие:\n{name}\n{schedule}"
                        )
                    except:
                        pass

                    await db.execute(
                        "INSERT INTO reminders VALUES (?, ?)",
                        (booking_id, str(now))
                    )
                    await db.commit()

        await asyncio.sleep(60)


# --- KEYBOARDS ---
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Записаться", callback_data="start")],
        [InlineKeyboardButton(text="💳 Абонементы", callback_data="abon")]
    ])


def directions_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Хип-хоп дети", callback_data="dir_hiphop_kids")],
        [InlineKeyboardButton(text="Хип-хоп взрослые", callback_data="dir_hiphop_adult")],
        [InlineKeyboardButton(text="Гёрли хип-хоп", callback_data="dir_girly")],
        [InlineKeyboardButton(text="Контемпорари", callback_data="dir_contempo")],
        [InlineKeyboardButton(text="Акробатика", callback_data="dir_acro")],
        [InlineKeyboardButton(text="Фристайл", callback_data="dir_freestyle")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")]
    ])


def groups_kb(groups):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{g[1]} | {g[2]}", callback_data=f"group_{g[0]}")]
        for g in groups
    ] + [[InlineKeyboardButton(text="⬅️ Назад", callback_data="start")]])


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
    await message.answer("Выберите действие👇", reply_markup=main_menu())


# --- НАПРАВЛЕНИЯ ---
@dp.callback_query(F.data == "start")
async def choose_direction(call: CallbackQuery):
    await call.message.delete()
    await call.message.answer("Выберите направление:", reply_markup=directions_kb())


# --- ГРУППЫ ---
@dp.callback_query(F.data.startswith("dir_"))
async def show_groups(call: CallbackQuery):
    mapping = {
        "dir_hiphop_kids": "Хип-хоп дети",
        "dir_hiphop_adult": "Хип-хоп взрослые",
        "dir_girly": "Гёрли",
        "dir_contempo": "Контемпорари",
        "dir_acro": "Акробатика",
        "dir_freestyle": "Фристайл"
    }

    groups = await get_groups_by_direction(mapping[call.data])
    await call.message.delete()
    await call.message.answer("Выберите время:", reply_markup=groups_kb(groups))


# --- ВЫБОР ---
@dp.callback_query(F.data.startswith("group_"))
async def select_group(call: CallbackQuery, state: FSMContext):
    gid = int(call.data.split("_")[1])
    group = await get_group(gid)

    if await count_in_group(gid) >= group[3]:
        await call.message.answer("❌ Группа заполнена")
        return

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
        "style": group[1],
        "user_id": message.from_user.id
    })

    bid = await add_booking(data)

    await bot.send_message(
        ADMIN_ID,
        f"Заявка #{bid}\n{data['fio']}\n{group[1]} {group[2]}",
        reply_markup=admin_kb(bid)
    )

    await message.answer("Заявка отправлена 🙌")
    await state.clear()


# --- АДМИН ---
@dp.callback_query(F.data.startswith("ok_"))
async def ok(call: CallbackQuery):
    bid = int(call.data.split("_")[1])
    booking = await get_booking(bid)

    await update_status(bid, "approved")
    await bot.send_message(booking[1], "✅ Вы записаны!")


@dp.callback_query(F.data.startswith("no_"))
async def no(call: CallbackQuery):
    bid = int(call.data.split("_")[1])
    booking = await get_booking(bid)

    await update_status(bid, "declined")
    await bot.send_message(booking[1], "❌ Отказ")


# --- RUN ---
async def main():
    await init_db()

    asyncio.create_task(reminder_worker())

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        INSERT OR IGNORE INTO groups VALUES
        (1,'Хип-хоп дети 6-8','Ср 17:00-18:00',20),
        (2,'Хип-хоп дети 6-8','Пт 17:00-18:00',20),
        (3,'Хип-хоп взрослые','Ср 17:00-18:00',20),
        (4,'Фристайл','Пт 16:00-17:00',20)
        """)
        await db.commit()

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
