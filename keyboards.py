from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🛒 Browse Accounts", callback_data="shop"),
        InlineKeyboardButton(text="📦 My Orders", callback_data="my_orders"),
    )
    builder.row(
        InlineKeyboardButton(text="💰 Balance", callback_data="balance"),
        InlineKeyboardButton(text="🆘 Support", callback_data="support"),
    )
    return builder.as_markup()


def category_kb(counts: dict) -> InlineKeyboardMarkup:
    """counts: {category_key: (label, count, price_from)}"""
    builder = InlineKeyboardBuilder()
    for key, (label, count, price) in counts.items():
        builder.row(
            InlineKeyboardButton(
                text=f"{label} — {count} available | from ${price}",
                callback_data=f"cat:{key}"
            )
        )
    builder.row(InlineKeyboardButton(text="🔙 Back", callback_data="main_menu"))
    return builder.as_markup()


def account_list_kb(accounts: list, page: int = 0, per_page: int = 5) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    start = page * per_page
    page_accounts = accounts[start:start + per_page]

    for acc in page_accounts:
        builder.row(
            InlineKeyboardButton(
                text=f"#{acc.id} — ${acc.price:.2f} — {acc.description or 'Verified Account'}",
                callback_data=f"acc:{acc.id}"
            )
        )

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ Prev", callback_data=f"page:{page-1}"))
    if start + per_page < len(accounts):
        nav.append(InlineKeyboardButton(text="Next ▶️", callback_data=f"page:{page+1}"))
    if nav:
        builder.row(*nav)

    builder.row(InlineKeyboardButton(text="🔙 Back to Categories", callback_data="shop"))
    return builder.as_markup()


def account_detail_kb(account_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💎 Pay with TON", callback_data=f"pay_ton:{account_id}"),
        InlineKeyboardButton(text="💳 Pay with Crypto", callback_data=f"pay_oxapay:{account_id}"),
    )
    builder.row(InlineKeyboardButton(text="🔙 Back", callback_data="shop"))
    return builder.as_markup()


def payment_check_kb(order_id: int, method: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ I've Paid — Check Now", callback_data=f"check_pay:{order_id}:{method}")
    )
    builder.row(
        InlineKeyboardButton(text="❌ Cancel Order", callback_data=f"cancel_order:{order_id}")
    )
    return builder.as_markup()


def back_to_main_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu"))
    return builder.as_markup()


def admin_kb() -> InlineKeyboardMarkup:
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
