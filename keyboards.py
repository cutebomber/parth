from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🛒 Browse Accounts", callback_data="shop"),
        InlineKeyboardButton(text="📦 My Orders", callback_data="my_orders"),
    )
    builder.row(
        InlineKeyboardButton(text="💰 Balance", callback_data="balance"),
        InlineKeyboardButton(text="🆘 Support", callback_data="support"),
    )
    return builder.as_markup()
