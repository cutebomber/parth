from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from db import Database

router = Router()

# This is the fixed price for all accounts — change in config if needed
ACCOUNT_PRICE = 15.00


def buy_confirm_kb():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💎 Pay with TON",    callback_data="buy_ton"),
        InlineKeyboardButton(text="💳 Pay with Crypto", callback_data="buy_oxapay"),
    )
    builder.row(InlineKeyboardButton(text="❌ Cancel", callback_data="buy_cancel"))
    return builder.as_markup()


@router.message(F.text == "🛒 Buy Account")
@router.message(Command("buy"))
async def msg_buy(message: Message, db: Database, config):
    count = await db.count_available()
    if count == 0:
        await message.answer(
            "😔 <b>Out of stock</b>\n\n"
            "No accounts available right now.\n"
            f"Contact {config.SUPPORT_USERNAME} to be notified when stock is back."
        )
        return

    await message.answer(
        f"🛒 <b>Buy Fragment Account</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Fragment verified\n"
        f"📲 OTP auto-delivered\n"
        f"🔒 Ready to use instantly\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💵 Price: <b>${config.ACCOUNT_PRICE:.2f}</b>\n"
        f"📦 In stock: <b>{count}</b>\n\n"
        f"Choose payment method to continue:",
        reply_markup=buy_confirm_kb()
    )


@router.callback_query(F.data == "buy_cancel")
async def cb_buy_cancel(call: CallbackQuery):
    await call.message.edit_text("❌ Purchase cancelled.")
    await call.answer()


@router.message(F.text == "📦 My Purchases")
async def msg_my_purchases(message: Message, db: Database):
    user = await db.get_user(message.from_user.id)
    if not user:
        await message.answer("Please send /start first.")
        return
    orders = await db.get_user_orders(user.id)
    delivered = [o for o in orders if o.status == "delivered"]
    if not orders:
        await message.answer("📦 <b>My Purchases</b>\n\nNo purchases yet — tap 🛒 Buy Account!")
        return

    status_emoji = {"pending": "⏳", "paid": "💳", "delivered": "✅", "cancelled": "❌"}
    lines = [f"📦 <b>My Purchases</b> ({len(delivered)} completed)\n"]
    for o in orders[:10]:
        e = status_emoji.get(o.status, "❓")
        lines.append(
            f"{e} Order #{o.id} — ${o.amount_usd:.2f}\n"
            f"   {o.status.upper()} · {o.created_at.strftime('%d %b %Y %H:%M')}"
        )
    await message.answer("\n\n".join(lines))
