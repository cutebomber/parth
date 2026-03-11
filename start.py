from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery

from db import Database
from keyboards import main_menu_kb

router = Router()

WELCOME_TEXT = """
👋 <b>Welcome to @ikycbot!</b>

🔐 The #1 shop for <b>Fragment-verified Telegram accounts</b>

━━━━━━━━━━━━━━━━━━━━━━
✅ All accounts verified via <b>Fragment.com</b>
⚡ Instant auto-delivery after payment
💎 Pay with <b>TON</b> or <b>crypto</b> (OxaPay)
🔒 Guaranteed working or support
━━━━━━━━━━━━━━━━━━━━━━

👇 Use the menu below to get started
"""


@router.message(CommandStart())
async def cmd_start(message: Message, db: Database):
    await db.get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name,
    )
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_kb())


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(call: CallbackQuery):
    await call.message.edit_text(WELCOME_TEXT, reply_markup=main_menu_kb())


@router.callback_query(F.data == "support")
async def cb_support(call: CallbackQuery, config):
    await call.message.edit_text(
        f"🆘 <b>Support</b>\n\nContact us: {config.SUPPORT_USERNAME}\n\nWe typically respond within 1 hour.",
    )
    await call.answer()


@router.callback_query(F.data == "balance")
async def cb_balance(call: CallbackQuery, db: Database):
    user = await db.get_user(call.from_user.id)
    await call.message.edit_text(
        f"💰 <b>Your Balance</b>\n\n"
        f"Current balance: <b>${user.balance:.2f}</b>\n"
        f"Total spent: <b>${user.total_spent:.2f}</b>",
    )
    await call.answer()
