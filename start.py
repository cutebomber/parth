from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

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


class TopupFSM(StatesGroup):
    amount = State()
    method = State()


@router.message(CommandStart())
async def cmd_start(message: Message, db: Database, state: FSMContext):
    await state.clear()
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
async def msg_add_balance(message: Message, state: FSMContext):
    await message.answer(
        "➕ <b>Add Balance</b>\n\n"
        "Enter the amount in <b>USDT</b> you want to add:\n"
        "Example: <code>25</code> or <code>10.50</code>"
    )
    await state.set_state(TopupFSM.amount)


@router.message(TopupFSM.amount)
async def fsm_topup_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.strip().replace("$", "").replace(",", ""))
        if amount < 1:
            await message.answer("❌ Minimum top-up is $1.00")
            return
        await state.update_data(amount=amount)

        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="💎 TON",    callback_data="topup_ton"),
            InlineKeyboardButton(text="💳 Crypto", callback_data="topup_oxapay"),
        )
        builder.row(InlineKeyboardButton(text="❌ Cancel", callback_data="topup_cancel"))

        await message.answer(
            f"➕ <b>Top Up ${amount:.2f} USDT</b>\n\n"
            f"Choose payment method:",
            reply_markup=builder.as_markup()
        )
        await state.set_state(TopupFSM.method)
    except ValueError:
        await message.answer("❌ Invalid amount. Please enter a number like <code>25</code>")


@router.callback_query(F.data == "topup_cancel")
async def cb_topup_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ Top-up cancelled.")
    await call.answer()


@router.callback_query(F.data.in_({"topup_ton", "topup_oxapay"}), TopupFSM.method)
async def cb_topup_pay(call: CallbackQuery, state: FSMContext, db: Database, config):
    data = await state.get_data()
    amount = data.get("amount", 0)
    method = call.data  # topup_ton or topup_oxapay
    await state.clear()

    if method == "topup_ton":
        from ton import TonPaymentClient
        ton_client = TonPaymentClient(config.TON_WALLET_ADDRESS, config.TON_API_KEY)
        ton_amount = await ton_client.usd_to_ton(amount)
        if not ton_amount:
            await call.answer("❌ Could not fetch TON price.", show_alert=True)
            return

        import time, hashlib
        memo = hashlib.md5(f"TOPUP-{call.from_user.id}-{int(time.time())}".encode()).hexdigest()[:12].upper()
        deeplink = ton_client.get_tonkeeper_link(ton_amount, memo)

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
            f"3. Paste memo in comment\n\n"
            f"⚠️ Balance credited automatically after confirmation.\n"
            f"Contact {config.SUPPORT_USERNAME} if not credited within 10 min.",
            reply_markup=builder.as_markup()
        )

    else:  # oxapay
        from oxapay import OxaPayClient
        oxapay = OxaPayClient(config.OXAPAY_API_KEY, config.OXAPAY_MERCHANT)
        invoice = await oxapay.create_invoice(
            amount=amount, currency="USDT",
            order_id=f"topup_{call.from_user.id}_{int(__import__('time').time())}",
            description=f"@ikycbot balance top-up",
            callback_url=config.OXAPAY_CALLBACK_URL,
        )
        if not invoice:
            await call.answer("❌ Payment gateway error. Try again.", show_alert=True)
            return

        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="💳 Pay Now", url=invoice.pay_link))

        await call.message.edit_text(
            f"💳 <b>Top Up with Crypto</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 Amount: <b>${amount:.2f} USDT</b>\n"
            f"⏱ Expires: 30 minutes\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Tap Pay Now to complete.\n"
            f"Balance credited automatically after confirmation.",
            reply_markup=builder.as_markup()
        )

    await call.answer()


# ── Help ─────────────────────────────────────

@router.message(F.text == "❓ Help")
async def msg_help(message: Message, config):
    await message.answer(
        f"❓ <b>Help & Support</b>\n\n"
        f"<b>How to buy:</b>\n"
        f"1. Tap 🛒 <b>Buy Account</b>\n"
        f"2. Pay with TON or crypto\n"
        f"3. Get phone number instantly\n"
        f"4. Login — OTP forwarded to you automatically 📲\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Add Balance:</b>\n"
        f"Top up your balance and use it for purchases.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆘 Support: {config.SUPPORT_USERNAME}"
    )
