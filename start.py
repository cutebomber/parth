from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from db import Database
from keyboards import main_menu_kb

router = Router()

WELCOME_TEXT = """
👋 <b>Welcome to @ikycbot!</b>

🔐 Buy <b>Fragment-verified Telegram accounts</b> instantly.

━━━━━━━━━━━━━━━━━━━━━━
➕ Add balance to your wallet
🛒 Buy an account with one tap
📲 OTP auto-delivered on login
━━━━━━━━━━━━━━━━━━━━━━

Use the menu below 👇
"""

TOPUP_AMOUNTS = [5, 10, 20, 50, 100]


class TopupFSM(StatesGroup):
    choosing_amount  = State()
    choosing_method  = State()
    waiting_ton      = State()
    waiting_oxapay   = State()


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
    orders    = await db.get_user_orders(user.id)
    delivered = [o for o in orders if o.status == "delivered"]
    handle    = f"@{message.from_user.username}" if message.from_user.username else "—"
    await message.answer(
        f"👤 <b>My Profile</b>\n\n"
        f"🙍 Name: {message.from_user.full_name}\n"
        f"🔗 Username: {handle}\n"
        f"🆔 ID: <code>{message.from_user.id}</code>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Balance: <b>${user.balance:.2f}</b>\n"
        f"💸 Total Spent: <b>${user.total_spent:.2f}</b>\n"
        f"✅ Accounts Bought: <b>{len(delivered)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )


# ── Add Balance ───────────────────────────────

@router.message(F.text == "➕ Add Balance")
async def msg_add_balance(message: Message, state: FSMContext):
    b = InlineKeyboardBuilder()
    for amt in TOPUP_AMOUNTS:
        b.button(text=f"${amt}", callback_data=f"topup_amt:{amt}")
    b.adjust(3)
    b.row(InlineKeyboardButton(text="✏️ Custom amount", callback_data="topup_custom"))
    await message.answer(
        f"➕ <b>Add Balance</b>\n\n"
        f"Select amount to add to your wallet:",
        reply_markup=b.as_markup()
    )
    await state.set_state(TopupFSM.choosing_amount)


@router.callback_query(F.data.startswith("topup_amt:"))
async def cb_topup_amount(call: CallbackQuery, state: FSMContext):
    amount = float(call.data.split(":")[1])
    await state.update_data(amount=amount)
    await _show_payment_methods(call.message, amount, edit=True)
    await state.set_state(TopupFSM.choosing_method)
    await call.answer()


@router.callback_query(F.data == "topup_custom")
async def cb_topup_custom(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text("✏️ Send the amount you want to add (e.g. <code>25</code>):")
    await state.set_state(TopupFSM.choosing_amount)
    await call.answer()


@router.message(TopupFSM.choosing_amount)
async def fsm_custom_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.strip().replace("$", ""))
        if amount < 1:
            await message.answer("❌ Minimum top-up is $1.")
            return
        await state.update_data(amount=amount)
        await _show_payment_methods(message, amount, edit=False)
        await state.set_state(TopupFSM.choosing_method)
    except ValueError:
        await message.answer("❌ Enter a valid number like <code>25</code>")


async def _show_payment_methods(target, amount: float, edit: bool):
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="💎 TON",    callback_data="pay_topup:ton"),
        InlineKeyboardButton(text="💳 Crypto", callback_data="pay_topup:oxapay"),
    )
    b.row(InlineKeyboardButton(text="❌ Cancel", callback_data="topup_cancel"))
    text = (
        f"➕ <b>Add ${amount:.2f} to wallet</b>\n\n"
        f"Choose payment method:"
    )
    if edit:
        await target.edit_text(text, reply_markup=b.as_markup())
    else:
        await target.answer(text, reply_markup=b.as_markup())


@router.callback_query(F.data == "topup_cancel")
async def cb_topup_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ Top-up cancelled.")
    await call.answer()


@router.callback_query(F.data.startswith("pay_topup:"))
async def cb_pay_topup(call: CallbackQuery, state: FSMContext, db: Database, config):
    method = call.data.split(":")[1]
    data   = await state.get_data()
    amount = data.get("amount", 0)

    if not amount:
        await call.answer("Session expired, start again.", show_alert=True)
        await state.clear()
        return

    if method == "ton":
        from ton import TonPaymentClient
        import time, hashlib
        ton_client = TonPaymentClient(config.TON_WALLET_ADDRESS, config.TON_API_KEY)
        ton_amount = await ton_client.usd_to_ton(amount)
        if not ton_amount:
            await call.answer("❌ Can't fetch TON price, try again.", show_alert=True)
            return
        memo = "BAL-" + hashlib.md5(f"{call.from_user.id}-{time.time()}".encode()).hexdigest()[:8].upper()
        await state.update_data(memo=memo, ton_amount=ton_amount, ts=int(time.time()), method="ton")

        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="💎 Open TonKeeper", url=ton_client.get_tonkeeper_link(ton_amount, memo)))
        b.row(InlineKeyboardButton(text="✅ I've Paid", callback_data="verify_topup"))
        b.row(InlineKeyboardButton(text="❌ Cancel",    callback_data="topup_cancel"))

        await call.message.edit_text(
            f"💎 <b>Top up ${amount:.2f} via TON</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💎 Send: <b>{ton_amount} TON</b>\n"
            f"📝 Memo: <code>{memo}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"1. Open TonKeeper\n"
            f"2. Send {ton_amount} TON\n"
            f"3. Add memo in comment\n"
            f"4. Tap ✅ I've Paid",
            reply_markup=b.as_markup()
        )
        await state.set_state(TopupFSM.waiting_ton)

    elif method == "oxapay":
        from oxapay import OxaPayClient
        oxapay = OxaPayClient(config.OXAPAY_API_KEY, config.OXAPAY_MERCHANT)
        invoice = await oxapay.create_invoice(
            amount=amount, currency="USDT",
            order_id=f"BAL-{call.from_user.id}-{int(__import__('time').time())}",
            description=f"@ikycbot balance top-up ${amount:.2f}",
            callback_url=config.OXAPAY_CALLBACK_URL,
        )
        if not invoice:
            await call.answer("❌ Payment gateway error, try again.", show_alert=True)
            return
        await state.update_data(invoice_id=invoice.invoice_id, method="oxapay")

        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="💳 Pay Now",   url=invoice.pay_link))
        b.row(InlineKeyboardButton(text="✅ I've Paid",  callback_data="verify_topup"))
        b.row(InlineKeyboardButton(text="❌ Cancel",    callback_data="topup_cancel"))

        await call.message.edit_text(
            f"💳 <b>Top up ${amount:.2f} via Crypto</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 Amount: <b>${amount:.2f} USDT</b>\n"
            f"⏱ Expires: 30 minutes\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Tap 💳 Pay Now then come back and tap ✅ I've Paid",
            reply_markup=b.as_markup()
        )
        await state.set_state(TopupFSM.waiting_oxapay)

    await call.answer()


@router.callback_query(F.data == "verify_topup")
async def cb_verify_topup(call: CallbackQuery, state: FSMContext, db: Database, config):
    data   = await state.get_data()
    method = data.get("method")
    amount = data.get("amount", 0)
    paid   = False

    await call.answer("🔍 Checking...", show_alert=False)

    if method == "ton":
        from ton import TonPaymentClient
        ton_client = TonPaymentClient(config.TON_WALLET_ADDRESS, config.TON_API_KEY)
        tx = await ton_client.verify_payment(
            memo=data.get("memo"),
            expected_ton=data.get("ton_amount"),
            since_timestamp=data.get("ts", 0) - 60,
        )
        if tx:
            paid = True

    elif method == "oxapay":
        from oxapay import OxaPayClient
        oxapay = OxaPayClient(config.OXAPAY_API_KEY, config.OXAPAY_MERCHANT)
        status = await oxapay.check_payment(data.get("invoice_id", ""))
        if status and OxaPayClient.is_paid(status):
            paid = True

    if paid:
        await db.add_balance(call.from_user.id, amount)
        user = await db.get_user(call.from_user.id)
        await state.clear()
        await call.message.edit_text(
            f"✅ <b>${amount:.2f} added to your wallet!</b>\n\n"
            f"💰 New balance: <b>${user.balance:.2f}</b>\n\n"
            f"Tap 🛒 Buy Account to use it."
        )
    else:
        await call.message.answer(
            "⏳ Payment not confirmed yet.\nWait a moment and try again."
        )


# ── Help ──────────────────────────────────────

@router.message(F.text == "❓ Help")
async def msg_help(message: Message, config):
    await message.answer(
        f"❓ <b>Help</b>\n\n"
        f"<b>How to buy:</b>\n"
        f"1. Tap ➕ Add Balance — top up your wallet\n"
        f"2. Tap 🛒 Buy Account — confirm with one tap\n"
        f"3. Enter the phone number on Telegram\n"
        f"4. OTP is sent here automatically 📲\n"
        f"5. Enter OTP + 2FA to complete login\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 TON via TonKeeper\n"
        f"💳 Crypto via OxaPay (USDT, BTC, ETH...)\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆘 Support: {config.SUPPORT_USERNAME}"
    )
