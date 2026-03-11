from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛒 Buy Account"), KeyboardButton(text="➕ Add Balance")],
            [KeyboardButton(text="👤 My Profile"),  KeyboardButton(text="📦 My Purchases")],
            [KeyboardButton(text="❓ Help")],
        ],
        resize_keyboard=True,
        persistent=True,
    )


def remove_kb() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()
