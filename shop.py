from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from db import Database, AccountCategory

router = Router()

TIER_META = {
    "standard": ("🔐", "Standard",  "Fragment-verified · fresh accounts"),
    "aged_30":  ("📅", "Aged 30+",  "Fragment-verified · 30+ days old"),
    "aged_90":  ("🏆", "Aged 90+",  "Fragment-verified · 90+ days old"),
    "premium":  ("⭐", "Premium",   "Fragment-verified + Telegram Premium"),
}


def shop_main_kb(tier_data: dict):
    builder = InlineKeyboardBuilder()
    for tier_key, (emoji, label, desc) in TIER_META.items():
        info = tier_data.get(tier_key)
        if info:
            count, min_price = info
            builder.row(InlineKeyboardButton(
                text=f"{emoji} {label} — {count} in stock · from ${min_price:.2f}",
                callback_data=f"tier:{tier_key}:0"
            ))
    builder.row(InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu"))
    return builder.as_markup()


def account_list_kb(accounts: list, tier: str, page: int, per_page: int = 5):
    builder = InlineKeyboardBuilder()
    start = page * per_page
    for acc in accounts[start:start + per_page]:
        flags = []
        if acc.has_2fa:
            flags.append("🔑2FA")
        if acc.has_username:
            flags.append("✏️@user")
        if acc.country_code:
            flags.append(acc.country_code)
        tag = " · ".join(flags) if flags else "clean"
        builder.row(InlineKeyboardButton(
            text=f"#{acc.id} · ${acc.price:.2f} · {tag}",
            callback_data=f"acc:{acc.id}"
        ))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ Prev", callback_data=f"tier:{tier}:{page-1}"))
    if start + per_page < len(accounts):
        nav.append(InlineKeyboardButton(text="Next ▶️", callback_data=f"tier:{tier}:{page+1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 Back to Shop", callback_data="shop"))
    return builder.as_markup()


def account_detail_kb(account_id: int):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💎 Pay with TON", callback_data=f"pay_ton:{account_id}"),
        InlineKeyboardButton(text="💳 Pay with Crypto", callback_data=f"pay_oxapay:{account_id}"),
    )
    builder.row(InlineKeyboardButton(text="🔙 Back to Shop", callback_data="shop"))
    return builder.as_markup()


@router.message(Command("shop"))
async def cmd_shop(message: Message, db: Database):
    await render_shop(message, db, edit=False)


@router.callback_query(F.data == "shop")
async def cb_shop(call: CallbackQuery, db: Database):
    await render_shop(call.message, db, edit=True)
    await call.answer()


async def render_shop(target, db: Database, edit: bool = True):
    tier_data = {}
    for tier_key in TIER_META:
        accs = await db.get_available_by_tier(tier_key)
        if accs:
            min_price = min(a.price for a in accs)
            tier_data[tier_key] = (len(accs), min_price)

    if not tier_data:
        text = "😔 <b>No accounts in stock right now.</b>\n\nCheck back soon or contact support."
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu"))
        if edit:
            await target.edit_text(text, reply_markup=kb.as_markup())
        else:
            await target.answer(text, reply_markup=kb.as_markup())
        return

    total = sum(v[0] for v in tier_data.values())
    text = (
        f"🛒 <b>Fragment Verified Accounts</b>\n\n"
        f"All accounts verified via <b>Fragment.com</b>\n"
        f"✅ Instant auto-delivery · 🔒 Guaranteed working\n\n"
        f"📦 <b>{total} accounts in stock</b> — pick a tier:"
    )
    if edit:
        await target.edit_text(text, reply_markup=shop_main_kb(tier_data))
    else:
        await target.answer(text, reply_markup=shop_main_kb(tier_data))


@router.callback_query(F.data.startswith("tier:"))
async def cb_tier(call: CallbackQuery, db: Database):
    parts = call.data.split(":")
    tier_key = parts[1]
    page = int(parts[2])
    if tier_key not in TIER_META:
        await call.answer("Invalid tier.", show_alert=True)
        return
    accounts = await db.get_available_by_tier(tier_key)
    if not accounts:
        await call.answer("No accounts in this tier right now!", show_alert=True)
        return
    emoji, label, desc = TIER_META[tier_key]
    text = (
        f"{emoji} <b>{label} Fragment Accounts</b>\n"
        f"<i>{desc}</i>\n\n"
        f"<b>{len(accounts)} available</b> — tap to view details:"
    )
    await call.message.edit_text(text, reply_markup=account_list_kb(accounts, tier_key, page))
    await call.answer()


@router.callback_query(F.data.startswith("acc:"))
async def cb_account_detail(call: CallbackQuery, db: Database):
    account_id = int(call.data.split(":")[1])
    acc = await db.get_account(account_id)
    if not acc or acc.status != "available":
        await call.answer("❌ Account no longer available!", show_alert=True)
        return
    emoji, tier_label, _ = TIER_META.get(acc.tier, ("🔐", acc.tier, ""))
    features = ["✅ Verified via Fragment.com"]
    if acc.account_age_days:
        features.append(f"📅 Account age: {acc.account_age_days} days")
    if acc.country_code:
        features.append(f"🌍 Country: {acc.country_code}")
    if acc.has_2fa:
        features.append("🔑 2FA password included")
    if acc.has_username:
        features.append("✏️ Has @username")
    if acc.session_string:
        features.append("🔗 Session string included")
    if acc.tdata_path:
        features.append("📁 TData file included")
    if acc.email:
        features.append("📧 Recovery email included")
    text = (
        f"{emoji} <b>{tier_label} Fragment Account #{acc.id}</b>\n\n"
        f"💵 Price: <b>${acc.price:.2f}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        + "\n".join(features) + "\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        + (f"📝 {acc.description}\n\n" if acc.description else "")
        + f"⚡ <b>Delivered instantly after payment</b>\n"
        f"Select payment method 👇"
    )
    await call.message.edit_text(text, reply_markup=account_detail_kb(account_id))
    await call.answer()


@router.callback_query(F.data == "my_orders")
async def cb_my_orders(call: CallbackQuery, db: Database):
    user = await db.get_user(call.from_user.id)
    if not user:
        await call.answer("Please /start the bot first.", show_alert=True)
        return
    orders = await db.get_user_orders(user.id)
    if not orders:
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="🛒 Browse Shop", callback_data="shop"))
        await call.message.edit_text(
            "📦 <b>My Orders</b>\n\nNo orders yet — head to the shop!",
            reply_markup=kb.as_markup()
        )
        await call.answer()
        return
    status_emoji = {
        "pending": "⏳", "paid": "💳", "delivered": "✅",
        "cancelled": "❌", "refunded": "🔄"
    }
    lines = ["📦 <b>My Orders</b>\n"]
    for o in orders[:10]:
        st = o.status.value if hasattr(o.status, "value") else o.status
        pm = o.payment_method.value if hasattr(o.payment_method, "value") else o.payment_method
        e = status_emoji.get(st, "❓")
        lines.append(
            f"{e} <b>Order #{o.id}</b> — ${o.amount_usd:.2f} via {pm.upper()}\n"
            f"   {st.upper()} · {o.created_at.strftime('%d %b %Y %H:%M')}"
        )
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🛒 Shop More", callback_data="shop"))
    kb.row(InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu"))
    await call.message.edit_text("\n\n".join(lines), reply_markup=kb.as_markup())
    await call.answer()
