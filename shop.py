from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from db import Database

router = Router()


def account_list_kb(accounts: list, page: int, per_page: int = 5):
    builder = InlineKeyboardBuilder()
    start = page * per_page
    for acc in accounts[start:start + per_page]:
        builder.row(InlineKeyboardButton(
            text=f"#{acc.id} · ${acc.price:.2f}" + (f" · {acc.description}" if acc.description else ""),
            callback_data=f"acc:{acc.id}"
        ))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ Prev", callback_data=f"accpage:{page-1}"))
    if start + per_page < len(accounts):
        nav.append(InlineKeyboardButton(text="Next ▶️", callback_data=f"accpage:{page+1}"))
    if nav:
        builder.row(*nav)
    return builder.as_markup()


def account_detail_kb(account_id: int):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💎 Pay with TON",    callback_data=f"pay_ton:{account_id}"),
        InlineKeyboardButton(text="💳 Pay with Crypto", callback_data=f"pay_oxapay:{account_id}"),
    )
    builder.row(InlineKeyboardButton(text="🔙 Back", callback_data="accpage:0"))
    return builder.as_markup()


async def render_shop(target: Message, db: Database):
    accounts = await db.get_available_accounts()
    if not accounts:
        await target.answer("😔 <b>No accounts available right now.</b>\n\nCheck back soon!")
        return
    text = (
        f"🛒 <b>Buy Fragment Account</b>\n\n"
        f"All accounts are <b>Fragment-verified</b>\n"
        f"✅ Auto OTP delivery · 🔒 2FA included\n\n"
        f"📦 <b>{len(accounts)} accounts available</b> — tap to view:"
    )
    await target.answer(text, reply_markup=account_list_kb(accounts, 0))


@router.message(F.text == "🛒 Buy Account")
async def msg_shop(message: Message, db: Database):
    await render_shop(message, db)


@router.message(Command("shop"))
async def cmd_shop(message: Message, db: Database):
    await render_shop(message, db)


@router.callback_query(F.data.startswith("accpage:"))
async def cb_accpage(call: CallbackQuery, db: Database):
    page = int(call.data.split(":")[1])
    accounts = await db.get_available_accounts()
    if not accounts:
        await call.message.edit_text("😔 No accounts available right now.")
        await call.answer()
        return
    text = (
        f"🛒 <b>Buy Fragment Account</b>\n\n"
        f"📦 <b>{len(accounts)} accounts available</b> — tap to view:"
    )
    await call.message.edit_text(text, reply_markup=account_list_kb(accounts, page))
    await call.answer()


@router.callback_query(F.data.startswith("acc:"))
async def cb_account_detail(call: CallbackQuery, db: Database):
    account_id = int(call.data.split(":")[1])
    acc = await db.get_account(account_id)
    if not acc or acc.status != "available":
        await call.answer("❌ Account no longer available!", show_alert=True)
        return

    text = (
        f"🔐 <b>Fragment Account #{acc.id}</b>\n\n"
        f"💵 Price: <b>${acc.price:.2f}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Verified via Fragment.com\n"
        f"📲 OTP auto-forwarded on login\n"
        f"🔑 2FA password included\n"
        + (f"📝 {acc.description}\n" if acc.description else "")
        + f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⚡ <b>Delivered instantly after payment</b>\n"
        f"Select payment method 👇"
    )
    await call.message.edit_text(text, reply_markup=account_detail_kb(account_id))
    await call.answer()


@router.message(F.text == "📦 My Purchases")
async def msg_my_purchases(message: Message, db: Database):
    user = await db.get_user(message.from_user.id)
    if not user:
        await message.answer("Please send /start first.")
        return
    orders = await db.get_user_orders(user.id)
    if not orders:
        await message.answer("📦 <b>My Purchases</b>\n\nNo purchases yet — tap 🛒 Buy Account to get started!")
        return
    status_emoji = {
        "pending": "⏳", "paid": "💳", "delivered": "✅",
        "cancelled": "❌", "refunded": "🔄"
    }
    lines = ["📦 <b>My Purchases</b>\n"]
    for o in orders[:10]:
        st = o.status if isinstance(o.status, str) else o.status.value
        pm = o.payment_method if isinstance(o.payment_method, str) else o.payment_method.value
        e  = status_emoji.get(st, "❓")
        lines.append(
            f"{e} <b>Order #{o.id}</b> — ${o.amount_usd:.2f} via {pm.upper()}\n"
            f"   {st.upper()} · {o.created_at.strftime('%d %b %Y %H:%M')}"
        )
    await message.answer("\n\n".join(lines))
