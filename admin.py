from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from db import Database

router = Router()


def is_admin(user_id: int, config) -> bool:
    return user_id in config.ADMIN_IDS


def admin_kb():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➕ Add Account",     callback_data="admin_add_account"),
        InlineKeyboardButton(text="📊 Stats",           callback_data="admin_stats"),
    )
    builder.row(
        InlineKeyboardButton(text="📋 Pending Orders",  callback_data="admin_pending"),
        InlineKeyboardButton(text="👥 Users",           callback_data="admin_users"),
    )
    return builder.as_markup()


class AddAccountFSM(StatesGroup):
    phone    = State()
    price    = State()
    session  = State()
    two_fa   = State()
    desc     = State()


@router.message(Command("admin"))
async def cmd_admin(message: Message, config):
    if not is_admin(message.from_user.id, config):
        return
    await message.answer("👑 <b>Admin Panel — @ikycbot</b>", reply_markup=admin_kb())


@router.callback_query(F.data == "admin_stats")
async def cb_stats(call: CallbackQuery, db: Database, config):
    if not is_admin(call.from_user.id, config):
        return
    from sqlalchemy import select, func
    from db import TelegramAccount, Order, User
    async with db.session() as s:
        total_users = (await s.execute(select(func.count()).select_from(User))).scalar()
        available   = (await s.execute(select(func.count()).select_from(TelegramAccount).where(TelegramAccount.status == "available"))).scalar()
        sold        = (await s.execute(select(func.count()).select_from(TelegramAccount).where(TelegramAccount.status == "sold"))).scalar()
        revenue     = (await s.execute(select(func.sum(Order.amount_usd)).where(Order.status == "delivered"))).scalar() or 0.0
    await call.message.edit_text(
        f"📊 <b>Stats</b>\n\n"
        f"👥 Users: <b>{total_users}</b>\n"
        f"📦 Available: <b>{available}</b>\n"
        f"✅ Sold: <b>{sold}</b>\n"
        f"💰 Revenue: <b>${revenue:.2f}</b>",
        reply_markup=admin_kb()
    )
    await call.answer()


@router.callback_query(F.data == "admin_pending")
async def cb_pending(call: CallbackQuery, db: Database, config):
    if not is_admin(call.from_user.id, config):
        return
    from sqlalchemy import select
    from db import Order
    async with db.session() as s:
        r = await s.execute(select(Order).where(Order.status == "pending").order_by(Order.created_at.desc()).limit(20))
        orders = r.scalars().all()
    if not orders:
        await call.message.edit_text("✅ No pending orders!", reply_markup=admin_kb())
        await call.answer()
        return
    lines = [f"⏳ <b>Pending ({len(orders)})</b>\n"]
    for o in orders:
        lines.append(f"#{o.id} · User {o.user_id} · ${o.amount_usd:.2f} · {o.payment_method.upper()}")
    await call.message.edit_text("\n".join(lines), reply_markup=admin_kb())
    await call.answer()


@router.callback_query(F.data == "admin_users")
async def cb_users(call: CallbackQuery, db: Database, config):
    if not is_admin(call.from_user.id, config):
        return
    from sqlalchemy import select
    from db import User
    async with db.session() as s:
        r = await s.execute(select(User).order_by(User.created_at.desc()).limit(15))
        users = r.scalars().all()
    lines = [f"👥 <b>Recent Users</b>\n"]
    for u in users:
        handle = f"@{u.username}" if u.username else str(u.telegram_id)
        lines.append(f"• {handle} · ${u.total_spent:.2f} spent")
    await call.message.edit_text("\n".join(lines), reply_markup=admin_kb())
    await call.answer()


# ── Add Account FSM ───────────────────────────

@router.callback_query(F.data == "admin_add_account")
async def cb_add_start(call: CallbackQuery, state: FSMContext, config):
    if not is_admin(call.from_user.id, config):
        return
    await call.message.answer(
        "➕ <b>Add Account</b>\n\n"
        "Step 1/5 — Send the <b>phone number</b> (e.g. +447123456789):"
    )
    await state.set_state(AddAccountFSM.phone)
    await call.answer()


@router.message(AddAccountFSM.phone)
async def fsm_phone(message: Message, state: FSMContext, config):
    if not is_admin(message.from_user.id, config):
        return
    if not message.text.strip().startswith("+"):
        await message.answer("❌ Must start with + and country code.")
        return
    await state.update_data(phone=message.text.strip())
    await message.answer("Step 2/5 — <b>Price in USD</b> (e.g. 15.00):")
    await state.set_state(AddAccountFSM.price)


@router.message(AddAccountFSM.price)
async def fsm_price(message: Message, state: FSMContext, config):
    if not is_admin(message.from_user.id, config):
        return
    try:
        price = float(message.text.strip())
        await state.update_data(price=price)
        await message.answer("Step 3/5 — <b>Session string</b> (Pyrogram) for OTP relay, or /skip:")
        await state.set_state(AddAccountFSM.session)
    except ValueError:
        await message.answer("❌ Invalid price.")


@router.message(AddAccountFSM.session)
async def fsm_session(message: Message, state: FSMContext, config):
    if not is_admin(message.from_user.id, config):
        return
    val = None if message.text.strip() == "/skip" else message.text.strip()
    await state.update_data(session=val)
    await message.answer("Step 4/5 — <b>2FA password</b>, or /skip:")
    await state.set_state(AddAccountFSM.two_fa)


@router.message(AddAccountFSM.two_fa)
async def fsm_two_fa(message: Message, state: FSMContext, config):
    if not is_admin(message.from_user.id, config):
        return
    val = None if message.text.strip() == "/skip" else message.text.strip()
    await state.update_data(two_fa=val)
    await message.answer("Step 5/5 — Short <b>description</b> (optional), or /skip:")
    await state.set_state(AddAccountFSM.desc)


@router.message(AddAccountFSM.desc)
async def fsm_desc(message: Message, state: FSMContext, db: Database, config):
    if not is_admin(message.from_user.id, config):
        return
    desc = None if message.text.strip() == "/skip" else message.text.strip()
    data = await state.get_data()
    acc = await db.add_account(
        phone_number=data["phone"],
        price=data["price"],
        session_string=data.get("session"),
        two_fa_password=data.get("two_fa"),
        description=desc,
    )
    await state.clear()
    await message.answer(
        f"✅ <b>Account #{acc.id} added!</b>\n\n"
        f"📱 Phone: <code>{acc.phone_number}</code>\n"
        f"💵 Price: <b>${acc.price:.2f}</b>\n"
        f"🔑 2FA: {'Yes ✅' if acc.two_fa_password else 'No'}\n"
        f"🔗 Session: {'Yes ✅' if acc.session_string else 'No ⚠️'}\n"
        f"Status: Available"
    )
