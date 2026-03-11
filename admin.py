import json
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from database.db import Database, AccountCategory

router = Router()

TIER_LABELS = {
    "standard": "🔐 Standard (fresh, Fragment verified)",
    "aged_30":  "📅 Aged 30+ days",
    "aged_90":  "🏆 Aged 90+ days",
    "premium":  "⭐ Premium + Fragment verified",
}


def is_admin(user_id: int, config) -> bool:
    return user_id in config.ADMIN_IDS


def admin_kb():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➕ Add Account", callback_data="admin_add_account"),
        InlineKeyboardButton(text="📊 Stats", callback_data="admin_stats"),
    )
    builder.row(
        InlineKeyboardButton(text="📋 Pending Orders", callback_data="admin_pending"),
        InlineKeyboardButton(text="👥 Users", callback_data="admin_users"),
    )
    return builder.as_markup()


# ── FSM States ──────────────────────────────────

class AddAccountFSM(StatesGroup):
    tier = State()
    phone = State()
    price = State()
    session = State()
    tdata = State()
    two_fa = State()
    email = State()
    country = State()
    age_days = State()
    description = State()
    confirm = State()


# ── Admin Panel ─────────────────────────────────

@router.message(Command("admin"))
async def cmd_admin(message: Message, config):
    if not is_admin(message.from_user.id, config):
        return
    await message.answer("👑 <b>Admin Panel — @ikycbot</b>", reply_markup=admin_kb())


@router.callback_query(F.data == "admin_stats")
async def cb_admin_stats(call: CallbackQuery, db: Database, config):
    if not is_admin(call.from_user.id, config):
        return

    from sqlalchemy import select, func
    from database.db import TelegramAccount, Order, User, AccountStatus, OrderStatus

    async with db.session() as s:
        total_users = (await s.execute(select(func.count()).select_from(User))).scalar()
        available = (await s.execute(
            select(func.count()).select_from(TelegramAccount)
            .where(TelegramAccount.status == AccountStatus.AVAILABLE)
        )).scalar()
        sold = (await s.execute(
            select(func.count()).select_from(TelegramAccount)
            .where(TelegramAccount.status == AccountStatus.SOLD)
        )).scalar()
        revenue = (await s.execute(
            select(func.sum(Order.amount_usd))
            .where(Order.status == OrderStatus.DELIVERED)
        )).scalar() or 0.0

    # Per-tier stock count
    tier_lines = []
    for tier_key, label in TIER_LABELS.items():
        accs = await db.get_available_by_tier(tier_key)
        tier_lines.append(f"  {label[:2]} {tier_key}: <b>{len(accs)}</b>")

    await call.message.edit_text(
        f"📊 <b>Bot Statistics</b>\n\n"
        f"👥 Total users: <b>{total_users}</b>\n"
        f"📦 Available: <b>{available}</b>\n"
        f"✅ Sold: <b>{sold}</b>\n"
        f"💰 Revenue: <b>${revenue:.2f}</b>\n\n"
        f"<b>Stock by tier:</b>\n" + "\n".join(tier_lines),
        reply_markup=admin_kb()
    )
    await call.answer()


@router.callback_query(F.data == "admin_pending")
async def cb_admin_pending(call: CallbackQuery, db: Database, config):
    if not is_admin(call.from_user.id, config):
        return

    from sqlalchemy import select
    from database.db import Order, OrderStatus

    async with db.session() as s:
        result = await s.execute(
            select(Order).where(Order.status == OrderStatus.PENDING)
            .order_by(Order.created_at.desc()).limit(20)
        )
        orders = result.scalars().all()

    if not orders:
        await call.message.edit_text("✅ No pending orders!", reply_markup=admin_kb())
        await call.answer()
        return

    lines = [f"⏳ <b>Pending Orders ({len(orders)})</b>\n"]
    for o in orders:
        pm = o.payment_method.value if hasattr(o.payment_method, "value") else o.payment_method
        lines.append(f"#{o.id} · User {o.user_id} · ${o.amount_usd:.2f} · {pm.upper()}")

    await call.message.edit_text("\n".join(lines), reply_markup=admin_kb())
    await call.answer()


@router.callback_query(F.data == "admin_users")
async def cb_admin_users(call: CallbackQuery, db: Database, config):
    if not is_admin(call.from_user.id, config):
        return

    from sqlalchemy import select
    from database.db import User

    async with db.session() as s:
        result = await s.execute(select(User).order_by(User.created_at.desc()).limit(15))
        users = result.scalars().all()

    lines = [f"👥 <b>Recent Users ({len(users)})</b>\n"]
    for u in users:
        handle = f"@{u.username}" if u.username else str(u.telegram_id)
        lines.append(f"• {handle} · ${u.total_spent:.2f} spent")

    await call.message.edit_text("\n".join(lines), reply_markup=admin_kb())
    await call.answer()


# ── Add Account FSM ─────────────────────────────

@router.callback_query(F.data == "admin_add_account")
async def cb_add_start(call: CallbackQuery, state: FSMContext, config):
    if not is_admin(call.from_user.id, config):
        return

    tier_text = "\n".join([f"<code>{k}</code> — {v}" for k, v in TIER_LABELS.items()])
    await call.message.answer(
        f"➕ <b>Add Fragment Account</b>\n\n"
        f"Step 1/9 — Send the <b>tier key</b>:\n\n{tier_text}"
    )
    await state.set_state(AddAccountFSM.tier)
    await call.answer()


@router.message(AddAccountFSM.tier)
async def fsm_tier(message: Message, state: FSMContext, config):
    if not is_admin(message.from_user.id, config):
        return
    if message.text.strip() not in TIER_LABELS:
        await message.answer(f"❌ Invalid tier. Choose from: {', '.join(TIER_LABELS.keys())}")
        return
    await state.update_data(tier=message.text.strip())
    await message.answer("Step 2/9 — <b>Phone number</b> (include country code, e.g. +44712345678):")
    await state.set_state(AddAccountFSM.phone)


@router.message(AddAccountFSM.phone)
async def fsm_phone(message: Message, state: FSMContext, config):
    if not is_admin(message.from_user.id, config):
        return
    phone = message.text.strip()
    if not phone.startswith("+"):
        await message.answer("❌ Phone must start with + and country code.")
        return
    await state.update_data(phone=phone)
    await message.answer("Step 3/9 — <b>Price in USD</b> (e.g. 12.50):")
    await state.set_state(AddAccountFSM.price)


@router.message(AddAccountFSM.price)
async def fsm_price(message: Message, state: FSMContext, config):
    if not is_admin(message.from_user.id, config):
        return
    try:
        price = float(message.text.strip())
        await state.update_data(price=price)
        await message.answer("Step 4/9 — <b>Session string</b> (Pyrogram/Telethon) or /skip:")
        await state.set_state(AddAccountFSM.session)
    except ValueError:
        await message.answer("❌ Invalid price. Example: 12.50")


@router.message(AddAccountFSM.session)
async def fsm_session(message: Message, state: FSMContext, config):
    if not is_admin(message.from_user.id, config):
        return
    val = None if message.text.strip() == "/skip" else message.text.strip()
    await state.update_data(session=val)
    await message.answer("Step 5/9 — <b>TData path/filename</b> (e.g. account_42.zip) or /skip:")
    await state.set_state(AddAccountFSM.tdata)


@router.message(AddAccountFSM.tdata)
async def fsm_tdata(message: Message, state: FSMContext, config):
    if not is_admin(message.from_user.id, config):
        return
    val = None if message.text.strip() == "/skip" else message.text.strip()
    await state.update_data(tdata=val)
    await message.answer("Step 6/9 — <b>2FA password</b> (if account has 2FA) or /skip:")
    await state.set_state(AddAccountFSM.two_fa)


@router.message(AddAccountFSM.two_fa)
async def fsm_two_fa(message: Message, state: FSMContext, config):
    if not is_admin(message.from_user.id, config):
        return
    val = None if message.text.strip() == "/skip" else message.text.strip()
    await state.update_data(two_fa=val)
    await message.answer("Step 7/9 — <b>Recovery email</b> or /skip:")
    await state.set_state(AddAccountFSM.email)


@router.message(AddAccountFSM.email)
async def fsm_email(message: Message, state: FSMContext, config):
    if not is_admin(message.from_user.id, config):
        return
    val = None if message.text.strip() == "/skip" else message.text.strip()
    await state.update_data(email=val)
    await message.answer("Step 8/9 — <b>Country code</b> (e.g. +44, +1, +7) or /skip:")
    await state.set_state(AddAccountFSM.country)


@router.message(AddAccountFSM.country)
async def fsm_country(message: Message, state: FSMContext, config):
    if not is_admin(message.from_user.id, config):
        return
    val = None if message.text.strip() == "/skip" else message.text.strip()
    await state.update_data(country=val)
    await message.answer("Step 9/9 — <b>Account age in days</b> (e.g. 45) or /skip:")
    await state.set_state(AddAccountFSM.age_days)


@router.message(AddAccountFSM.age_days)
async def fsm_age(message: Message, state: FSMContext, config):
    if not is_admin(message.from_user.id, config):
        return
    txt = message.text.strip()
    age = None
    if txt != "/skip":
        try:
            age = int(txt)
        except ValueError:
            await message.answer("❌ Enter a number or /skip")
            return
    await state.update_data(age=age)
    await message.answer("Optional — short <b>description</b> for buyers, or /skip:")
    await state.set_state(AddAccountFSM.description)


@router.message(AddAccountFSM.description)
async def fsm_description(message: Message, state: FSMContext, db: Database, config):
    if not is_admin(message.from_user.id, config):
        return
    desc = None if message.text.strip() == "/skip" else message.text.strip()
    data = await state.get_data()

    has_2fa = data.get("two_fa") is not None
    acc = await db.add_account(
        category=AccountCategory.FRAGMENT_VERIFIED,
        tier=data["tier"],
        phone_number=data["phone"],
        price=data["price"],
        session_string=data.get("session"),
        tdata_path=data.get("tdata"),
        two_fa_password=data.get("two_fa"),
        email=data.get("email"),
        country_code=data.get("country"),
        account_age_days=data.get("age"),
        has_2fa=has_2fa,
        has_username=False,
        description=desc,
    )

    await state.clear()
    await message.answer(
        f"✅ <b>Account #{acc.id} added successfully!</b>\n\n"
        f"Tier: {TIER_LABELS[acc.tier]}\n"
        f"Phone: <code>{acc.phone_number}</code>\n"
        f"Price: <b>${acc.price:.2f}</b>\n"
        f"2FA: {'Yes' if acc.has_2fa else 'No'}\n"
        f"Status: Available ✅"
    )
