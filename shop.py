from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from db import Database

router = Router()


def confirm_buy_kb():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="✅ Confirm Purchase", callback_data="confirm_buy"))
    b.row(InlineKeyboardButton(text="❌ Cancel",           callback_data="cancel_buy"))
    return b.as_markup()


@router.message(F.text == "🛒 Buy Account")
@router.message(Command("buy"))
async def msg_buy(message: Message, db: Database, config):
    count = await db.count_available()
    user  = await db.get_user(message.from_user.id)

    if not user:
        await message.answer("Please send /start first.")
        return

    if count == 0:
        await message.answer(
            "😔 <b>Out of stock</b>\n\n"
            f"No accounts available right now.\n"
            f"Contact {config.SUPPORT_USERNAME} to be notified."
        )
        return

    price = config.ACCOUNT_PRICE
    bal   = user.balance

    if bal < price:
        needed = price - bal
        await message.answer(
            f"💳 <b>Insufficient Balance</b>\n\n"
            f"Account price: <b>${price:.2f}</b>\n"
            f"Your balance: <b>${bal:.2f}</b>\n"
            f"You need: <b>${needed:.2f} more</b>\n\n"
            f"Tap ➕ Add Balance to top up first."
        )
        return

    await message.answer(
        f"🛒 <b>Confirm Purchase</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Fragment verified account\n"
        f"📲 OTP auto-delivered on login\n"
        f"🔒 Ready to use instantly\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💵 Price: <b>${price:.2f}</b>\n"
        f"💰 Your balance: <b>${bal:.2f}</b>\n"
        f"💰 After purchase: <b>${bal - price:.2f}</b>\n\n"
        f"Tap confirm to complete purchase:",
        reply_markup=confirm_buy_kb()
    )


@router.callback_query(F.data == "confirm_buy")
async def cb_confirm_buy(call: CallbackQuery, db: Database, config):
    from db import TelegramAccount
    from sqlalchemy import select

    user  = await db.get_user(call.from_user.id)
    price = config.ACCOUNT_PRICE

    # Re-check balance
    if not user or user.balance < price:
        await call.answer("❌ Insufficient balance!", show_alert=True)
        return

    # Grab account
    acc = await db.get_available_account()
    if not acc:
        await call.answer("❌ Out of stock!", show_alert=True)
        return

    # Reserve + deduct balance
    await db.reserve_account(acc.id)
    await db.deduct_balance(user.telegram_id, price)

    # Create order
    order = await db.create_order(
        user_id=user.id, account_id=acc.id,
        payment_method="balance", amount_usd=price
    )

    # Deliver
    from aiogram import Bot
    bot = call.bot
    await deliver_account(order.id, call.from_user.id, db, bot, config)

    await call.message.edit_text(
        "✅ <b>Purchase confirmed!</b>\n\n"
        "Your account is ready — check the message below 📲"
    )
    await call.answer()


@router.callback_query(F.data == "cancel_buy")
async def cb_cancel_buy(call: CallbackQuery):
    await call.message.edit_text("❌ Purchase cancelled.")
    await call.answer()


@router.message(F.text == "📦 My Purchases")
async def msg_my_purchases(message: Message, db: Database):
    user = await db.get_user(message.from_user.id)
    if not user:
        await message.answer("Please send /start first.")
        return
    orders = await db.get_user_orders(user.id)
    if not orders:
        await message.answer("📦 <b>My Purchases</b>\n\nNo purchases yet — tap 🛒 Buy Account!")
        return
    status_emoji = {"pending": "⏳", "paid": "💳", "delivered": "✅", "cancelled": "❌"}
    lines = ["📦 <b>My Purchases</b>\n"]
    for o in orders[:10]:
        e = status_emoji.get(o.status, "❓")
        lines.append(
            f"{e} Order #{o.id} — ${o.amount_usd:.2f}\n"
            f"   {o.status.upper()} · {o.created_at.strftime('%d %b %Y %H:%M')}"
        )
    await message.answer("\n\n".join(lines))


async def deliver_account(order_id, telegram_id, db, bot, config):
    from otp_relay import start_otp_listener
    import asyncio

    order = await db.get_order(order_id)
    acc   = await db.get_account(order.account_id)

    await db.mark_account_sold(acc.id)
    await db.update_order_status(order_id, "paid")
    await db.update_order_status(order_id, "delivered")

    await db.create_otp_request(
        order_id=order_id, buyer_tg_id=telegram_id,
        account_id=acc.id, phone=acc.phone_number,
    )

    if acc.session_string:
        asyncio.create_task(
            start_otp_listener(acc.phone_number, acc.session_string, bot, db, config)
        )

    await bot.send_message(
        telegram_id,
        f"✅ <b>Account Delivered!</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📱 Phone: <code>{acc.phone_number}</code>\n"
        + (f"🔑 2FA: <code>{acc.two_fa_password}</code>\n" if acc.two_fa_password else "")
        + f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>How to login:</b>\n"
        f"1. Open Telegram on another device\n"
        f"2. Enter the phone number above\n"
        f"3. OTP will be <b>sent here automatically</b> 📲\n"
        f"4. Enter OTP + 2FA password\n\n"
        f"⚠️ Login now — OTP relay is active!\n"
        f"🆘 Issues? {config.SUPPORT_USERNAME}"
    )

    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"💰 <b>Sale!</b> Order #{order_id}\n"
                f"Account #{acc.id} · Buyer: {telegram_id}\n"
                f"${order.amount_usd:.2f} via balance"
            )
        except Exception:
            pass
