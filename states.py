from aiogram.fsm.state import StatesGroup, State


class BookingForm(StatesGroup):
    fio = State()
    phone = State()
    age = State()
    style = State()