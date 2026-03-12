import time
import hashlib
import asyncio
import logging
from aiogram import Router, F
from aiogram.filters import CommandStart

from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from db import Database
from keyboards import main_menu_kb

router = Router()
logger = logging.getLogger(__name__)

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


# amount stored in callback_data directly


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
    delivered = [o for o in orders if o.status == "delivered"]
    handle = f"@{message.from_user.username}" if message.from_user.username else "—"
    await message.answer(
        f"👤 <b>My Profile</b>\n\n"
        f"🙍 Name: {message.from_user.full_name}\n"
        f"🔗 Username: {handle}\n"
        f"🆔 ID: <code>{message.from_user.id}</code>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Balance: <b>${user.balance:.2f}</b>\n"
        f"💸 Total Spent: <b>${user.total_spent:.2f}</b>\n"
        f"✅ Completed Orders: <b>{len(delivered)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )


# ── Add Balance ───────────────────────────────

@router.message(F.text == "➕ Add Balance")
async def msg_add_balance(message: Message):
    await message.answer(
        "➕ <b>Add Balance</b>\n\n"
        "Enter the amount in <b>USDT</b> you want to add:\n"
        "Example: <code>25</code> or <code>10.50</code>\n\n"
        "Just type the number and send it 👇"
    )


@router.message(F.text.regexp(r'^\$?[0-9]+(\.[0-9]{1,2})?$'))
async def msg_topup_amount(message: Message):
    try:
        amount = float(message.text.strip().replace("$", "").replace(",", ""))
        if amount < 1:
            await message.answer("❌ Minimum top-up is $1.00")
            return
        amount_str = f"{amount:.2f}"
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="💎 TON",    callback_data=f"tup_ton:{amount_str}"),
            InlineKeyboardButton(text="💳 Crypto", callback_data=f"tup_ox:{amount_str}"),
        )
        builder.row(InlineKeyboardButton(text="❌ Cancel", callback_data="tup_cancel"))
        await message.answer(
            f"➕ <b>Top Up ${amount:.2f} USDT</b>\n\nChoose payment method:",
            reply_markup=builder.as_markup()
        )
    except ValueError:
        await message.answer("❌ Invalid amount. Enter a number like <code>25</code>")


@router.callback_query(F.data == "tup_cancel")
async def cb_topup_cancel(call: CallbackQuery):
    await call.message.edit_text("❌ Top-up cancelled.")
    await call.answer()


@router.callback_query(F.data.startswith("tup_ton:"))
async def cb_topup_ton(call: CallbackQuery, db: Database, config):
    amount = float(call.data.split(":")[1])
    user = await db.get_user(call.from_user.id)
    if not user:
        await call.answer("Please /start first.", show_alert=True)
        return

    from ton import TonPaymentClient
    ton_client = TonPaymentClient(config.TON_WALLET_ADDRESS, config.TON_API_KEY)
    ton_amount = await ton_client.usd_to_ton(amount)
    if not ton_amount:
        await call.answer("❌ Could not fetch TON price. Try again.", show_alert=True)
        return

    memo = "TB" + hashlib.md5(f"{call.from_user.id}-{time.time()}".encode()).hexdigest()[:10].upper()
    deeplink = ton_client.get_tonkeeper_link(ton_amount, memo)

    await db.create_topup(
        user_id=user.id,
        telegram_id=call.from_user.id,
        amount_usd=amount,
        payment_method="ton",
        payment_id=memo,
    )

    asyncio.create_task(
        watch_ton_topup(memo, ton_amount, amount, call.from_user.id, user.id, db, call.bot.token, config)
    )

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💎 Open TonKeeper", url=deeplink))

    await call.message.edit_text(
        f"💎 <b>Top Up with TON</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 Amount: <b>{ton_amount} TON</b> (${amount:.2f})\n"
        f"📝 Memo: <code>{memo}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"1. Open TonKeeper\n"
        f"2. Send <b>{ton_amount} TON</b>\n"
        f"3. Paste memo in comment field\n\n"
        f"✅ Balance credited automatically!",
        reply_markup=builder.as_markup()
    )
    await call.answer()


@router.callback_query(F.data.startswith("tup_ox:"))
async def cb_topup_oxapay(call: CallbackQuery, db: Database, config):
    amount = float(call.data.split(":")[1])
    user = await db.get_user(call.from_user.id)
    if not user:
        await call.answer("Please /start first.", show_alert=True)
        return

    from oxapay import OxaPayClient
    oxapay = OxaPayClient(config.OXAPAY_API_KEY, config.OXAPAY_MERCHANT)
    track_order_id = f"topup_{user.id}_{int(time.time())}"
    invoice = await oxapay.create_invoice(
        amount=amount,
        currency="USDT",
        order_id=track_order_id,
        description="@ikycbot balance top-up",
        callback_url=config.OXAPAY_CALLBACK_URL,
    )
    if not invoice:
        await call.answer("❌ Payment gateway error. Try again.", show_alert=True)
        return

    await db.create_topup(
        user_id=user.id,
        telegram_id=call.from_user.id,
        amount_usd=amount,
        payment_method="oxapay",
        payment_id=invoice.invoice_id,
    )

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💳 Pay Now", url=invoice.pay_link))

    await call.message.edit_text(
        f"💳 <b>Top Up with Crypto</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 Amount: <b>${amount:.2f} USDT</b>\n"
        f"⏱ Expires: 30 minutes\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Tap Pay Now to complete.\n"
        f"✅ Balance credited automatically!",
        reply_markup=builder.as_markup()
    )
    await call.answer()


async def watch_ton_topup(memo: str, ton_amount: float, usd_amount: float,
                           telegram_id: int, user_id: int, db: Database,
                           bot_token: str, config):
    from ton import TonPaymentClient
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    ton_client = TonPaymentClient(config.TON_WALLET_ADDRESS, config.TON_API_KEY)
    start_ts = int(time.time())
    deadline = start_ts + 1800  # 30 min
    attempts = 0

    logger.info(f"[TOPUP] Watching memo={memo} amount={ton_amount} TON user={telegram_id}")

    while time.time() < deadline:
        await asyncio.sleep(30)
        attempts += 1
        try:
            logger.info(f"[TOPUP] Check #{attempts} for memo={memo}")
            txs_raw = await ton_client.get_transactions(limit=50)
            logger.info(f"[TOPUP] Got {len(txs_raw)} transactions from wallet")

            tx = await ton_client.verify_payment(
                memo=memo,
                expected_ton=ton_amount,
                since_timestamp=start_ts - 60,
            )
            if tx:
                logger.info(f"[TOPUP] ✅ Payment found for memo={memo}")
                topup = await db.get_pending_topup_by_memo(memo)
                if not topup:
                    logger.error(f"[TOPUP] No pending topup found for memo={memo}")
                    return
                credited = await db.credit_topup(topup.id)
                if credited:
                    user = await db.get_user_by_id(user_id)
                    logger.info(f"[TOPUP] Credited ${usd_amount} to user {telegram_id}, new balance=${user.balance}")
                    bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode="HTML"))
                    try:
                        await bot.send_message(
                            telegram_id,
                            f"✅ <b>Balance Topped Up!</b>\n\n"
                            f"💰 Added: <b>${usd_amount:.2f}</b>\n"
                            f"💳 New balance: <b>${user.balance:.2f}</b>"
                        )
                    finally:
                        await bot.session.close()
                else:
                    logger.error(f"[TOPUP] credit_topup returned None for topup_id={topup.id}")
                return
            else:
                # Log recent tx memos to debug mismatch
                for tx in txs_raw[:5]:
                    msg = tx.get("in_msg", {})
                    comment = msg.get("message", "")
                    val = int(msg.get("value", 0)) / 1e9
                    utime = tx.get("utime", 0)
                    logger.info(f"[TOPUP] Recent tx: memo='{comment}' val={val} TON time={utime}")
        except Exception as e:
            logger.error(f"[TOPUP] Watch error: {e}", exc_info=True)

    logger.warning(f"[TOPUP] Watcher expired for memo={memo} after {attempts} attempts")


# ── Help ─────────────────────────────────────

@router.message(F.text == "❓ Help")
async def msg_help(message: Message, config):
    await message.answer(
        f"❓ <b>Help & Support</b>\n\n"
        f"<b>How to buy:</b>\n"
        f"1. Tap 🛒 <b>Buy Account</b>\n"
        f"2. Pay with TON or crypto\n"
        f"3. Get phone number instantly\n"
        f"4. Login — OTP forwarded automatically 📲\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Add Balance:</b>\n"
        f"Enter any USDT amount, pay, balance auto-credited.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆘 Support: {config.SUPPORT_USERNAME}"
    )


@router.message(F.text == "/checkbalance")
async def cmd_check_balance(message: Message, db: Database):
    user = await db.get_user(message.from_user.id)
    if not user:
        await message.answer("Please /start first.")
        return
    await message.answer(f"💰 Your current balance: <b>${user.balance:.2f}</b>")
