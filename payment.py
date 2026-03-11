import asyncio
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


# ── TON ───────────────────────────────────────

@router.callback_query(F.data == "buy_ton")
async def cb_buy_ton(call: CallbackQuery, db: Database, ton_client: TonPaymentClient, config):
    acc = await db.get_available_account()
    if not acc:
        await call.answer("❌ Out of stock!", show_alert=True)
        return

    user = await db.get_user(call.from_user.id)
    ton_amount = await ton_client.usd_to_ton(config.ACCOUNT_PRICE)
    if not ton_amount:
        await call.answer("❌ Could not fetch TON price, try again.", show_alert=True)
        return

    order = await db.create_order(user_id=user.id, account_id=acc.id, payment_method="ton", amount_usd=config.ACCOUNT_PRICE)
    await db.reserve_account(acc.id)

    memo = ton_client.generate_payment_memo(order.id)
    pending_ton[order.id] = {"memo": memo, "ton_amount": ton_amount, "timestamp": int(time.time()), "account_id": acc.id}

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💎 Open TonKeeper", url=ton_client.get_tonkeeper_link(ton_amount, memo)))
    builder.row(InlineKeyboardButton(text="✅ I've Paid", callback_data=f"check_pay:{order.id}:ton"))
    builder.row(InlineKeyboardButton(text="❌ Cancel",    callback_data=f"cancel_order:{order.id}"))

    await call.message.edit_text(
        f"💎 <b>Pay with TON</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 Amount: <b>{ton_amount} TON</b> (${config.ACCOUNT_PRICE:.2f})\n"
        f"📝 Memo: <code>{memo}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"1. Open TonKeeper\n"
        f"2. Send <b>{ton_amount} TON</b>\n"
        f"3. Paste memo in comment field\n"
        f"4. Tap ✅ I've Paid\n\n"
        f"⚠️ Memo is required!",
        reply_markup=builder.as_markup()
    )
    await call.answer()


# ── OxaPay ────────────────────────────────────

@router.callback_query(F.data == "buy_oxapay")
async def cb_buy_oxapay(call: CallbackQuery, db: Database, oxapay: OxaPayClient, config):
    acc = await db.get_available_account()
    if not acc:
        await call.answer("❌ Out of stock!", show_alert=True)
        return

    user = await db.get_user(call.from_user.id)
    order = await db.create_order(user_id=user.id, account_id=acc.id, payment_method="oxapay", amount_usd=config.ACCOUNT_PRICE)
    await db.reserve_account(acc.id)

    invoice = await oxapay.create_invoice(
        amount=config.ACCOUNT_PRICE, currency="USDT",
        order_id=str(order.id), description="@ikycbot — Fragment Account",
        callback_url=config.OXAPAY_CALLBACK_URL,
    )
    if not invoice:
        await db.set_account_available(acc.id)
        await db.update_order_status(order.id, "cancelled")
        await call.answer("❌ Payment gateway error. Try again.", show_alert=True)
        return

    await db.update_order_status(order.id, "pending", payment_id=invoice.invoice_id)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💳 Pay Now",   url=invoice.pay_link))
    builder.row(InlineKeyboardButton(text="✅ I've Paid",  callback_data=f"check_pay:{order.id}:oxapay"))
    builder.row(InlineKeyboardButton(text="❌ Cancel",    callback_data=f"cancel_order:{order.id}"))

    await call.message.edit_text(
        f"💳 <b>Pay with Crypto</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 Amount: <b>${config.ACCOUNT_PRICE:.2f} USDT</b>\n"
        f"⏱ Expires: 30 minutes\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Tap 💳 Pay Now then come back and tap ✅ I've Paid",
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

    await call.answer("🔍 Checking...", show_alert=False)
    paid = False

    if method == "oxapay" and order.payment_id:
        data = await oxapay.check_payment(order.payment_id)
        if data and OxaPayClient.is_paid(data):
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
        await call.message.edit_text(
            "✅ <b>Payment confirmed!</b>\n\n"
            "Your account is being prepared — check your messages! 📲"
        )
    else:
        await call.message.answer("⏳ Not confirmed yet. Wait a moment and try again.")


# ── Deliver ───────────────────────────────────

async def deliver_account(order_id: int, telegram_id: int, db: Database, bot: Bot, config):
    order = await db.get_order(order_id)
    acc   = await db.get_account(order.account_id)

    await db.update_order_status(order_id, "paid")
    await db.mark_account_sold(acc.id)
    await db.update_order_status(order_id, "delivered")
    pending_ton.pop(order_id, None)

    # Create OTP relay entry so bot knows to forward OTP to this buyer
    await db.create_otp_request(
        order_id=order_id,
        buyer_tg_id=telegram_id,
        account_id=acc.id,
        phone=acc.phone_number,
    )

    # Start Pyrogram listener on this account to catch incoming OTP
    if acc.session_string:
        asyncio.create_task(
            start_otp_listener(acc.phone_number, acc.session_string, bot, db, config)
        )

    # Send simple confirmation — no account details exposed
    await bot.send_message(
        telegram_id,
        f"✅ <b>Purchase Confirmed!</b>\n\n"
        f"Your Fragment account is ready.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📲 <b>Now open Telegram</b> (another device or app) and sign in with:\n\n"
        f"📱 <code>{acc.phone_number}</code>\n\n"
        f"The login OTP will be <b>sent to you here automatically</b> the moment Telegram sends it.\n"
        + (f"🔑 2FA Password: <code>{acc.two_fa_password}</code>\n" if acc.two_fa_password else "")
        + f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ Start the login now while OTP relay is active!\n"
        f"🆘 Issues? {config.SUPPORT_USERNAME}"
    )

    # Notify admins
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"💰 <b>Sale!</b> Order #{order_id}\n"
                f"Account #{acc.id} · Buyer: {telegram_id}\n"
                f"${order.amount_usd:.2f} via {order.payment_method}"
            )
        except Exception:
            pass


# ── Cancel ────────────────────────────────────

@router.callback_query(F.data.startswith("cancel_order:"))
async def cb_cancel(call: CallbackQuery, db: Database):
    order_id = int(call.data.split(":")[1])
    order = await db.get_order(order_id)
    if not order or order.status in ("paid", "delivered"):
        await call.answer("Cannot cancel.", show_alert=True)
        return
    await db.update_order_status(order_id, "cancelled")
    await db.set_account_available(order.account_id)
    pending_ton.pop(order_id, None)
    await call.message.edit_text("❌ Order cancelled.")
    await call.answer()
