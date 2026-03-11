from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message

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


# ── My Profile ────────────────────────────────

@router.message(F.text == "👤 My Profile")
async def msg_profile(message: Message, db: Database):
    user = await db.get_user(message.from_user.id)
    if not user:
        await message.answer("Please send /start first.")
        return

    orders = await db.get_user_orders(user.id)
    delivered = [o for o in orders if (o.status.value if hasattr(o.status, "value") else o.status) == "delivered"]

    handle = f"@{message.from_user.username}" if message.from_user.username else "No username"

    await message.answer(
        f"👤 <b>My Profile</b>\n\n"
        f"🙍 Name: {message.from_user.full_name}\n"
        f"🔗 Username: {handle}\n"
        f"🆔 Telegram ID: <code>{message.from_user.id}</code>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Balance: <b>${user.balance:.2f}</b>\n"
        f"💸 Total Spent: <b>${user.total_spent:.2f}</b>\n"
        f"✅ Completed Orders: <b>{len(delivered)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )


# ── Add Balance ───────────────────────────────

@router.message(F.text == "➕ Add Balance")
async def msg_add_balance(message: Message, config):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💎 Top up with TON",    callback_data="topup_ton"),
        InlineKeyboardButton(text="💳 Top up with Crypto", callback_data="topup_oxapay"),
    )

    await message.answer(
        f"➕ <b>Add Balance</b>\n\n"
        f"Choose an amount and payment method to top up your balance.\n\n"
        f"Your balance is used to instantly purchase accounts without re-entering payment details.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Select top-up method:",
        reply_markup=builder.as_markup()
    )


# ── Help ─────────────────────────────────────

@router.message(F.text == "❓ Help")
async def msg_help(message: Message, config):
    await message.answer(
        f"❓ <b>Help & Support</b>\n\n"
        f"<b>How it works:</b>\n"
        f"1. Tap 🛒 <b>Buy Account</b> to browse\n"
        f"2. Pick a tier and account\n"
        f"3. Pay with TON or crypto\n"
        f"4. Receive credentials instantly ⚡\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Payment methods:</b>\n"
        f"💎 TON via TonKeeper\n"
        f"💳 Crypto via OxaPay (USDT, BTC, ETH...)\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Need help?</b>\n"
        f"Contact support: {config.SUPPORT_USERNAME}\n"
        f"Response time: within 1 hour"
    )
