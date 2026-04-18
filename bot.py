import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from db import *
from states import BookingForm
from keyboards import *

import os

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

TOKEN = "8715454752:AAHkMyw_E_pSdSjmHI605KCdWnGhtG5cnlg"
ADMIN_ID = 5420031708

bot = Bot(TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# --- СТАРТ ---
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
        reply_markup=back("back_main")
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
    await state.update_data(age=message.text)
    await message.answer("Стиль:")
    await state.set_state(BookingForm.style)


@dp.message(BookingForm.style)
async def style(message: Message, state: FSMContext):
    data = await state.get_data()

    data.update({
        "style": message.text,
        "user_id": message.from_user.id
    })

    booking_id = await add_booking(data)

    text = f"""
Заявка #{booking_id}

ФИО: {data['fio']}
Телефон: {data['phone']}
Возраст: {data['age']}
Стиль: {data['style']}
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


# --- ЗАПУСК ---
async def main():
    await init_db()

    # добавим группы один раз
    async with aiosqlite.connect("dance.db") as db:
        await db.execute("""
        INSERT OR IGNORE INTO groups (id, name, schedule, limit_count)
        VALUES 
        (1, 'Хип-хоп дети 6-8', 'Ср 17:00', 15),
        (2, 'Контемпорари 7-12', 'Сб 11:00', 10)
        """)
        await db.commit()

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
