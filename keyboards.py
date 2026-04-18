from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💃 Записаться", callback_data="start")],
        [InlineKeyboardButton(text="💳 Абонементы", callback_data="abon")]
    ])


def back(where):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅ Назад", callback_data=where)]
    ])


def groups_kb(groups):
    kb = []
    for g in groups:
        kb.append([InlineKeyboardButton(
            text=f"{g[1]} | {g[2]}",
            callback_data=f"group_{g[0]}"
        )])
    kb.append([InlineKeyboardButton(text="⬅ Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def admin_kb(booking_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"ok_{booking_id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"no_{booking_id}")]
    ])