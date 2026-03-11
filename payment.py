import time
import logging
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from db import Database
from oxapay import OxaPayClient
from ton import TonPaymentClient
from otp_relay import start_otp_listener

router = Router()
logger = logging.getLogger(__name__)

pending_ton: dict[int, dict] = {}


# ── TON Payment ───────────────────────────────

@router.callback_query(F.data.startswith("pay_ton:"))
async def cb_pay_ton(call: CallbackQuery, db: Database, ton_client: TonPaymentClient):
    account_id = int(call.data.split(":")[1])
    acc = await db.get_account(account_id)
    if not acc or acc.status != "available":
        await call.answer("❌ Account no longer available!", show_alert=True)
        return

    user = await db.get_user(call.from_user.id)
    ton_amount = await ton_client.usd_to_ton(acc.price)
    if not ton_amount:
        await call.answer("❌ Could not fetch TON price, try again.", show_alert=True)
        return

    order = await db.create_order(
        user_id=user.id, account_id=acc.id,
        payment_method="ton", amount_usd=acc.price,
    )
    await db.reserve_account(account_id)

    memo = ton_client.generate_payment_memo(order.id)
    pending_ton[order.id] = {"memo": memo, "ton_amount": ton_amount, "timestamp": int(time.time())}

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💎 Open TonKeeper", url=ton_client.get_tonkeeper_link(ton_amount, memo)))
    builder.row(InlineKeyboardButton(text="✅ I've Paid", callback_data=f"check_pay:{order.id}:ton"))
    builder.row(InlineKeyboardButton(text="❌ Cancel",    callback_data=f"cancel_order:{order.id}"))

    await call.message.edit_text(
        f"💎 <b>Pay with TON</b>\n\n"
        f"Order #{order.id}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 Price: <b>${acc.price:.2f}</b>\n"
        f"💎 Amount: <b>{ton_amount} TON</b>\n"
        f"📝 Memo: <code>{memo}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"1. Open TonKeeper\n"
        f"2. Send <b>{ton_amount} TON</b>\n"
        f"3. <b>Add memo</b> in comment field!\n"
        f"4. Tap ✅ I've Paid",
        reply_markup=builder.as_markup()
    )
    await call.answer()


# ── OxaPay Payment ────────────────────────────

@router.callback_query(F.data.startswith("pay_oxapay:"))
async def cb_pay_oxapay(call: CallbackQuery, db: Database, oxapay: OxaPayClient, config):
    account_id = int(call.data.split(":")[1])
    acc = await db.get_account(account_id)
    if not acc or acc.status != "available":
        await call.answer("❌ Account no longer available!", show_alert=True)
        return

    user = await db.get_user(call.from_user.id)
    order = await db.create_order(
        user_id=user.id, account_id=acc.id,
        payment_method="oxapay", amount_usd=acc.price,
    )
    await db.reserve_account(account_id)

    invoice = await oxapay.create_invoice(
        amount=acc.price, currency="USDT",
        order_id=str(order.id),
        description=f"@ikycbot — Account #{acc.id}",
        callback_url=config.OXAPAY_CALLBACK_URL,
    )
    if not invoice:
        await call.answer("❌ Payment gateway error. Try again.", show_alert=True)
        return

    await db.update_order_status(order.id, "pending", payment_id=invoice.invoice_id)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💳 Pay Now",  url=invoice.pay_link))
    builder.row(InlineKeyboardButton(text="✅ I've Paid", callback_data=f"check_pay:{order.id}:oxapay"))
    builder.row(InlineKeyboardButton(text="❌ Cancel",   callback_data=f"cancel_order:{order.id}"))

    await call.message.edit_text(
        f"💳 <b>Pay with Crypto (OxaPay)</b>\n\n"
        f"Order #{order.id}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 Amount: <b>${acc.price:.2f} USDT</b>\n"
        f"🆔 Invoice: <code>{invoice.invoice_id}</code>\n"
        f"⏱ Expires: 30 minutes\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Tap 💳 Pay Now to complete payment",
        reply_markup=builder.as_markup()
    )
    await call.answer()


# ── Check Payment ─────────────────────────────

@router.callback_query(F.data.startswith("check_pay:"))
async def cb_check_payment(call: CallbackQuery, db: Database, bot: Bot,
                            oxapay: OxaPayClient, ton_client: TonPaymentClient, config):
    parts = call.data.split(":")
    order_id, method = int(parts[1]), parts[2]

    order = await db.get_order(order_id)
    if not order:
        await call.answer("Order not found!", show_alert=True)
        return
    if order.status == "delivered":
        await call.answer("✅ Already delivered!", show_alert=True)
        return

    await call.answer("🔍 Checking payment...", show_alert=False)
    paid = False

    if method == "oxapay" and order.payment_id:
        status_data = await oxapay.check_payment(order.payment_id)
        if status_data and OxaPayClient.is_paid(status_data):
            paid = True

    elif method == "ton":
        info = pending_ton.get(order_id)
        if info:
            tx = await ton_client.verify_payment(
                memo=info["memo"], expected_ton=info["ton_amount"],
                since_timestamp=info["timestamp"] - 60
            )
            if tx:
                paid = True
                await db.update_order_status(order_id, "paid", payment_id=str(tx.get("transaction_id", "")))

    if paid:
        await deliver_account(order_id, call.from_user.id, db, bot, config)
    else:
        await call.message.answer(
            "⏳ Payment not confirmed yet.\n\nWait a moment and try again."
        )


# ── Deliver Account ───────────────────────────

async def deliver_account(order_id: int, telegram_id: int, db: Database, bot: Bot, config):
    order = await db.get_order(order_id)
    acc   = await db.get_account(order.account_id)

    await db.update_order_status(order_id, "paid")
    await db.mark_account_sold(acc.id)
    await db.update_order_status(order_id, "delivered")
    pending_ton.pop(order_id, None)

    # Create OTP relay session
    await db.create_otp_request(
        order_id=order_id,
        buyer_tg_id=telegram_id,
        account_id=acc.id,
        phone=acc.phone_number,
    )

    # Start Pyrogram listener to catch the OTP when buyer tries to login
    if acc.session_string:
        asyncio.create_task(
            start_otp_listener(acc.phone_number, acc.session_string, bot, db, config)
        )

    # Send account details to buyer
    msg = (
        f"✅ <b>Payment Confirmed! Order #{order_id}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📱 Phone Number: <code>{acc.phone_number}</code>\n"
    )
    if acc.two_fa_password:
        msg += f"🔑 2FA Password: <code>{acc.two_fa_password}</code>\n"
    msg += (
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>How to login:</b>\n"
        f"1. Open Telegram and enter the phone number\n"
        f"2. Telegram will send an OTP — <b>this bot will forward it to you automatically</b> 📲\n"
        f"3. Enter the OTP to login\n"
        f"4. Enter the 2FA password above when prompted\n\n"
        f"⚠️ <b>Start the login process now</b> — OTP relay is active!\n"
        f"🆘 Issues? {config.SUPPORT_USERNAME}"
    )
    await bot.send_message(telegram_id, msg)

    # Notify admins
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"💰 <b>New Sale!</b>\n"
                f"Order #{order_id} | Account #{acc.id} ({acc.phone_number})\n"
                f"Buyer: {telegram_id} | ${order.amount_usd:.2f} via {order.payment_method}"
            )
        except Exception:
            pass


# ── Cancel Order ──────────────────────────────

@router.callback_query(F.data.startswith("cancel_order:"))
async def cb_cancel_order(call: CallbackQuery, db: Database):
    order_id = int(call.data.split(":")[1])
    order = await db.get_order(order_id)
    if not order or order.status in ("paid", "delivered"):
        await call.answer("Cannot cancel this order.", show_alert=True)
        return
    await db.update_order_status(order_id, "cancelled")
    from sqlalchemy import select
    from db import TelegramAccount
    async with db.session() as s:
        r = await s.execute(select(TelegramAccount).where(TelegramAccount.id == order.account_id))
        acc = r.scalar_one_or_none()
        if acc and acc.status == "reserved":
            acc.status = "available"
            await s.commit()
    pending_ton.pop(order_id, None)
    await call.message.edit_text("❌ Order cancelled.")
    await call.answer()


import asyncio
