import asyncio
import time
import logging
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.db import Database, OrderStatus, PaymentMethod
from payments.oxapay import OxaPayClient
from payments.ton import TonPaymentClient
from utils.keyboards import payment_check_kb, back_to_main_kb

router = Router()
logger = logging.getLogger(__name__)

# In-memory store for pending TON payments {order_id: {memo, ton_amount, timestamp}}
pending_ton: dict[int, dict] = {}


# ──────────────────────────────────────────────
# TON PAYMENT
# ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("pay_ton:"))
async def cb_pay_ton(call: CallbackQuery, db: Database, ton_client: TonPaymentClient):
    account_id = int(call.data.split(":")[1])
    acc = await db.get_account(account_id)

    if not acc or acc.status.value != "available":
        await call.answer("❌ Account no longer available!", show_alert=True)
        return

    user = await db.get_user(call.from_user.id)
    ton_amount = await ton_client.usd_to_ton(acc.price)

    if not ton_amount:
        await call.answer("❌ Could not fetch TON price, try again.", show_alert=True)
        return

    # Create order
    order = await db.create_order(
        user_id=user.id,
        account_id=acc.id,
        payment_method=PaymentMethod.TON,
        amount_usd=acc.price,
    )
    await db.reserve_account(account_id)

    memo = ton_client.generate_payment_memo(order.id)
    pending_ton[order.id] = {
        "memo": memo,
        "ton_amount": ton_amount,
        "timestamp": int(time.time()),
    }

    deeplink = ton_client.get_tonkeeper_link(ton_amount, memo)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💎 Open TonKeeper", url=deeplink))
    builder.row(InlineKeyboardButton(text="✅ I've Paid", callback_data=f"check_pay:{order.id}:ton"))
    builder.row(InlineKeyboardButton(text="❌ Cancel", callback_data=f"cancel_order:{order.id}"))

    await call.message.edit_text(
        f"💎 <b>Pay with TON</b>\n\n"
        f"Order #{order.id} — Account #{acc.id}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 Price: <b>${acc.price:.2f}</b>\n"
        f"💎 Amount: <b>{ton_amount} TON</b>\n"
        f"📝 Memo/Comment: <code>{memo}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 <b>Steps:</b>\n"
        f"1. Click 'Open TonKeeper' or send manually\n"
        f"2. Send exactly <b>{ton_amount} TON</b>\n"
        f"3. <b>Include memo</b> in the comment field!\n"
        f"4. Press 'I've Paid' to verify\n\n"
        f"⚠️ Memo is required for auto-verification!",
        reply_markup=builder.as_markup()
    )
    await call.answer()


# ──────────────────────────────────────────────
# OXAPAY PAYMENT
# ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("pay_oxapay:"))
async def cb_pay_oxapay(call: CallbackQuery, db: Database, oxapay: OxaPayClient, config):
    account_id = int(call.data.split(":")[1])
    acc = await db.get_account(account_id)

    if not acc or acc.status.value != "available":
        await call.answer("❌ Account no longer available!", show_alert=True)
        return

    user = await db.get_user(call.from_user.id)

    order = await db.create_order(
        user_id=user.id,
        account_id=acc.id,
        payment_method=PaymentMethod.OXAPAY,
        amount_usd=acc.price,
    )
    await db.reserve_account(account_id)

    invoice = await oxapay.create_invoice(
        amount=acc.price,
        currency="USDT",
        order_id=str(order.id),
        description=f"@ikycbot — Account #{acc.id}",
        callback_url=config.OXAPAY_CALLBACK_URL,
    )

    if not invoice:
        await call.answer("❌ Payment gateway error. Try again.", show_alert=True)
        # Revert reservation
        from database.db import AccountStatus
        await db.reserve_account(account_id)  # Will be reverted on cancel
        return

    await db.update_order_status(order.id, OrderStatus.PENDING, payment_id=invoice.invoice_id)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💳 Pay Now", url=invoice.pay_link))
    builder.row(InlineKeyboardButton(text="✅ I've Paid", callback_data=f"check_pay:{order.id}:oxapay"))
    builder.row(InlineKeyboardButton(text="❌ Cancel", callback_data=f"cancel_order:{order.id}"))

    await call.message.edit_text(
        f"💳 <b>Pay with Crypto (OxaPay)</b>\n\n"
        f"Order #{order.id} — Account #{acc.id}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 Amount: <b>${acc.price:.2f} USDT</b>\n"
        f"🆔 Invoice: <code>{invoice.invoice_id}</code>\n"
        f"⏱ Expires in: 30 minutes\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Supports: BTC, ETH, USDT, LTC, and more\n\n"
        f"Click 'Pay Now' to open payment page 👇",
        reply_markup=builder.as_markup()
    )
    await call.answer()


# ──────────────────────────────────────────────
# CHECK PAYMENT
# ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("check_pay:"))
async def cb_check_payment(call: CallbackQuery, db: Database, bot: Bot,
                            oxapay: OxaPayClient, ton_client: TonPaymentClient, config):
    parts = call.data.split(":")
    order_id = int(parts[1])
    method = parts[2]

    order = await db.get_order(order_id)
    if not order:
        await call.answer("Order not found!", show_alert=True)
        return

    if order.status == OrderStatus.DELIVERED:
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
                memo=info["memo"],
                expected_ton=info["ton_amount"],
                since_timestamp=info["timestamp"] - 60
            )
            if tx:
                paid = True
                await db.update_order_status(order_id, OrderStatus.PAID, payment_id=tx.get("transaction_id", ""))

    if paid:
        await deliver_account(order_id, call.from_user.id, db, bot, config)
    else:
        await call.message.answer(
            "⏳ Payment not confirmed yet.\n\n"
            "Please complete the payment and try again in a moment. "
            "If you already paid, wait 1–2 minutes for confirmation."
        )


async def deliver_account(order_id: int, telegram_id: int, db: Database, bot: Bot, config):
    """Deliver account details to user after confirmed payment."""
    order = await db.get_order(order_id)
    acc = await db.get_account(order.account_id)

    # Mark as paid & delivered
    await db.update_order_status(order_id, OrderStatus.PAID)
    await db.mark_account_sold(acc.id)
    await db.update_order_status(order_id, OrderStatus.DELIVERED)

    # Remove from pending TON
    pending_ton.pop(order_id, None)

    # Build delivery message
    delivery_lines = [
        f"✅ <b>Payment Confirmed!</b>",
        f"🎉 <b>Order #{order_id} — Fragment Account #{acc.id}</b>\n",
        f"━━━━━━━━━━━━━━━━━━━━━━",
        f"📱 Phone Number: <code>{acc.phone_number}</code>",
    ]

    if acc.two_fa_password:
        delivery_lines.append(f"🔑 2FA Password: <code>{acc.two_fa_password}</code>")
    if acc.email:
        delivery_lines.append(f"📧 Recovery Email: <code>{acc.email}</code>")
    if acc.session_string:
        delivery_lines.append(
            f"\n🔗 <b>Session String</b> (Pyrogram/Telethon):\n"
            f"<code>{acc.session_string}</code>"
        )
    if acc.tdata_path:
        delivery_lines.append(f"\n📁 <b>TData File:</b> {acc.tdata_path}")
    if acc.extra_info:
        delivery_lines.append(f"\nℹ️ Notes: {acc.extra_info}")

    delivery_lines += [
        f"\n━━━━━━━━━━━━━━━━━━━━━━",
        f"⚠️ <b>Save these credentials immediately!</b>",
        f"📋 Screenshot or copy now — this message won't repeat.",
        f"\n🆘 Any issues? Contact {config.SUPPORT_USERNAME}",
    ]

    await bot.send_message(telegram_id, "\n".join(delivery_lines))

    # Notify admins
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"💰 <b>New Sale!</b>\n"
                f"Order #{order_id} | Account #{acc.id}\n"
                f"User: {telegram_id}\n"
                f"Amount: ${order.amount_usd:.2f}\n"
                f"Method: {order.payment_method.value}"
            )
        except Exception:
            pass


# ──────────────────────────────────────────────
# CANCEL ORDER
# ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("cancel_order:"))
async def cb_cancel_order(call: CallbackQuery, db: Database):
    order_id = int(call.data.split(":")[1])
    order = await db.get_order(order_id)

    if not order or order.status in (OrderStatus.PAID, OrderStatus.DELIVERED):
        await call.answer("Cannot cancel this order.", show_alert=True)
        return

    await db.update_order_status(order_id, OrderStatus.CANCELLED)

    # Release the reserved account back to available
    from database.db import AccountStatus
    from sqlalchemy import select
    async with db.session() as s:
        from database.db import TelegramAccount
        result = await s.execute(select(TelegramAccount).where(TelegramAccount.id == order.account_id))
        acc = result.scalar_one_or_none()
        if acc and acc.status == AccountStatus.RESERVED:
            acc.status = AccountStatus.AVAILABLE
            await s.commit()

    pending_ton.pop(order_id, None)

    await call.message.edit_text(
        "❌ Order cancelled. The account has been released back to the shop.\n\n"
        "Feel free to browse again!",
        reply_markup=back_to_main_kb()
    )
    await call.answer()
