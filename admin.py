from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from db import Database

router = Router()


def is_admin(uid, config): return uid in config.ADMIN_IDS


def admin_kb():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="➕ Add Account", callback_data="admin_add"),
          InlineKeyboardButton(text="📊 Stats",       callback_data="admin_stats"))
    b.row(InlineKeyboardButton(text="📋 Pending",     callback_data="admin_pending"),
          InlineKeyboardButton(text="👥 Users",       callback_data="admin_users"))
    return b.as_markup()


class AddFSM(StatesGroup):
    phone  = State()
    twofa  = State()
    session= State()


@router.message(Command("admin"))
async def cmd_admin(message: Message, config):
    if not is_admin(message.from_user.id, config): return
    await message.answer("👑 <b>Admin Panel</b>", reply_markup=admin_kb())


@router.callback_query(F.data == "admin_stats")
async def cb_stats(call: CallbackQuery, db: Database, config):
    if not is_admin(call.from_user.id, config): return
    from sqlalchemy import select, func
    from db import TelegramAccount, Order, User
    async with db.session() as s:
        users     = (await s.execute(select(func.count()).select_from(User))).scalar()
        available = (await s.execute(select(func.count()).select_from(TelegramAccount).where(TelegramAccount.status == "available"))).scalar()
        sold      = (await s.execute(select(func.count()).select_from(TelegramAccount).where(TelegramAccount.status == "sold"))).scalar()
        revenue   = (await s.execute(select(func.sum(Order.amount_usd)).where(Order.status == "delivered"))).scalar() or 0.0
    await call.message.edit_text(
        f"📊 <b>Stats</b>\n\n"
        f"👥 Users: <b>{users}</b>\n"
        f"📦 In stock: <b>{available}</b>\n"
        f"✅ Sold: <b>{sold}</b>\n"
        f"💰 Revenue: <b>${revenue:.2f}</b>\n"
        f"💵 Account price: <b>${config.ACCOUNT_PRICE:.2f}</b>",
        reply_markup=admin_kb()
    )
    await call.answer()


@router.callback_query(F.data == "admin_pending")
async def cb_pending(call: CallbackQuery, db: Database, config):
    if not is_admin(call.from_user.id, config): return
    from sqlalchemy import select
    from db import Order
    async with db.session() as s:
        r = await s.execute(select(Order).where(Order.status == "pending").order_by(Order.created_at.desc()).limit(20))
        orders = r.scalars().all()
    if not orders:
        await call.message.edit_text("✅ No pending orders!", reply_markup=admin_kb())
    else:
        lines = [f"⏳ <b>Pending ({len(orders)})</b>\n"]
        for o in orders:
            lines.append(f"#{o.id} · User {o.user_id} · ${o.amount_usd:.2f} · {o.payment_method.upper()}")
        await call.message.edit_text("\n".join(lines), reply_markup=admin_kb())
    await call.answer()


@router.callback_query(F.data == "admin_users")
async def cb_users(call: CallbackQuery, db: Database, config):
    if not is_admin(call.from_user.id, config): return
    from sqlalchemy import select
    from db import User
    async with db.session() as s:
        r = await s.execute(select(User).order_by(User.created_at.desc()).limit(15))
        users = r.scalars().all()
    lines = ["👥 <b>Recent Users</b>\n"]
    for u in users:
        handle = f"@{u.username}" if u.username else str(u.telegram_id)
        lines.append(f"• {handle} · ${u.total_spent:.2f} spent · {'🚫' if u.is_banned else '✅'}")
    await call.message.edit_text("\n".join(lines), reply_markup=admin_kb())
    await call.answer()


# ── Add Account FSM ───────────────────────────

@router.callback_query(F.data == "admin_add")
async def cb_add(call: CallbackQuery, state: FSMContext, config):
    if not is_admin(call.from_user.id, config): return
    await call.message.answer(
        "➕ <b>Add Account</b>\n\n"
        "Step 1/3 — Send the <b>phone number</b>:\n"
        "Example: <code>+447123456789</code>"
    )
    await state.set_state(AddFSM.phone)
    await call.answer()


@router.message(AddFSM.phone)
async def fsm_phone(message: Message, state: FSMContext, config):
    if not is_admin(message.from_user.id, config): return
    phone = message.text.strip()
    if not phone.startswith("+"):
        await message.answer("❌ Must start with +"); return
    await state.update_data(phone=phone)
    await message.answer("Step 2/3 — <b>2FA password</b> (if set), or /skip:")
    await state.set_state(AddFSM.twofa)


@router.message(AddFSM.twofa)
async def fsm_twofa(message: Message, state: FSMContext, config):
    if not is_admin(message.from_user.id, config): return
    val = None if message.text.strip() == "/skip" else message.text.strip()
    await state.update_data(twofa=val)
    await message.answer(
        "Step 3/3 — <b>Pyrogram session string</b>:\n\n"
        "Don't have one? Run this on your PC:\n"
        "<code>pip install pyrogram tgcrypto</code>\n"
        "<code>python -c \"from pyrogram import Client; Client(':memory:').start()\"</code>\n\n"
        "Or send /skip to add without session (OTP relay won't work):"
    )
    await state.set_state(AddFSM.session)


@router.message(AddFSM.session)
async def fsm_session(message: Message, state: FSMContext, db: Database, config):
    if not is_admin(message.from_user.id, config): return
    session = None if message.text.strip() == "/skip" else message.text.strip()
    data = await state.get_data()

    # Check if phone already exists
    existing = await db.get_account_by_phone(data["phone"])
    if existing:
        await message.answer(f"⚠️ Phone {data['phone']} already exists (Account #{existing.id})")
        await state.clear()
        return

    acc = await db.add_account(
        phone_number=data["phone"],
        session_string=session,
        two_fa_password=data.get("twofa"),
        price=config.ACCOUNT_PRICE,
    )
    await state.clear()
    await message.answer(
        f"✅ <b>Account #{acc.id} added!</b>\n\n"
        f"📱 {acc.phone_number}\n"
        f"🔑 2FA: {'✅' if acc.two_fa_password else '❌'}\n"
        f"🔗 Session: {'✅' if acc.session_string else '❌ No OTP relay'}\n"
        f"💵 Price: ${acc.price:.2f}\n"
        f"Status: Available ✅"
    )
