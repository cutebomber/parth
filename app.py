"""
@ikycbot Web Admin Panel — FastAPI backend
Run with: uvicorn webpanel.app:app --host 0.0.0.0 --port 8080 --reload
"""
import sys
import json
from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
import secrets

from db import (
    Database, User, TelegramAccount, Order, Transaction,
    AccountStatus, OrderStatus, AccountCategory, PaymentMethod
)
from config import Config

app = FastAPI(title="@ikycbot Admin Panel", docs_url=None, redoc_url=None)
config = Config()
db = Database(config.DATABASE_URL)
security = HTTPBasic()

PANEL_USER = config.PANEL_USER
PANEL_PASS = config.PANEL_PASS

TIER_LABELS = {
    "standard": "Standard",
    "aged_30":  "Aged 30+",
    "aged_90":  "Aged 90+",
    "premium":  "Premium",
}


@app.on_event("startup")
async def startup():
    await db.init()


def auth(credentials: HTTPBasicCredentials = Depends(security)):
    ok = (
        secrets.compare_digest(credentials.username, PANEL_USER) and
        secrets.compare_digest(credentials.password, PANEL_PASS)
    )
    if not ok:
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic"})
    return credentials.username


# ── STATS ────────────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def api_stats(_=Depends(auth)):
    async with db.session() as s:
        total_users    = (await s.execute(select(func.count()).select_from(User))).scalar()
        total_accounts = (await s.execute(select(func.count()).select_from(TelegramAccount))).scalar()
        available      = (await s.execute(select(func.count()).select_from(TelegramAccount).where(TelegramAccount.status == AccountStatus.AVAILABLE))).scalar()
        sold           = (await s.execute(select(func.count()).select_from(TelegramAccount).where(TelegramAccount.status == AccountStatus.SOLD))).scalar()
        revenue        = (await s.execute(select(func.sum(Order.amount_usd)).where(Order.status == OrderStatus.DELIVERED))).scalar() or 0.0
        pending_orders = (await s.execute(select(func.count()).select_from(Order).where(Order.status == OrderStatus.PENDING))).scalar()
        total_orders   = (await s.execute(select(func.count()).select_from(Order))).scalar()

        # Revenue last 7 days
        week_ago = datetime.utcnow() - timedelta(days=7)
        week_rev = (await s.execute(
            select(func.sum(Order.amount_usd))
            .where(Order.status == OrderStatus.DELIVERED)
            .where(Order.paid_at >= week_ago)
        )).scalar() or 0.0

        # Revenue last 30 days
        month_ago = datetime.utcnow() - timedelta(days=30)
        month_rev = (await s.execute(
            select(func.sum(Order.amount_usd))
            .where(Order.status == OrderStatus.DELIVERED)
            .where(Order.paid_at >= month_ago)
        )).scalar() or 0.0

        # Per-tier stock
        tier_stock = {}
        for tier in ["standard", "aged_30", "aged_90", "premium"]:
            cnt = (await s.execute(
                select(func.count()).select_from(TelegramAccount)
                .where(TelegramAccount.status == AccountStatus.AVAILABLE)
                .where(TelegramAccount.tier == tier)
            )).scalar()
            tier_stock[tier] = cnt

        # New users last 7 days
        new_users = (await s.execute(
            select(func.count()).select_from(User).where(User.created_at >= week_ago)
        )).scalar()

    return {
        "total_users": total_users,
        "new_users_7d": new_users,
        "total_accounts": total_accounts,
        "available": available,
        "sold": sold,
        "revenue_total": round(revenue, 2),
        "revenue_7d": round(week_rev, 2),
        "revenue_30d": round(month_rev, 2),
        "pending_orders": pending_orders,
        "total_orders": total_orders,
        "tier_stock": tier_stock,
    }


# ── USERS ─────────────────────────────────────────────────────────────────────

@app.get("/api/users")
async def api_users(page: int = 0, limit: int = 20, search: str = "", _=Depends(auth)):
    async with db.session() as s:
        q = select(User).order_by(User.created_at.desc())
        if search:
            q = q.where(
                User.username.ilike(f"%{search}%") |
                User.full_name.ilike(f"%{search}%")
            )
        total = (await s.execute(select(func.count()).select_from(q.subquery()))).scalar()
        result = await s.execute(q.offset(page * limit).limit(limit))
        users = result.scalars().all()

    return {
        "total": total,
        "users": [
            {
                "id": u.id,
                "telegram_id": u.telegram_id,
                "username": u.username,
                "full_name": u.full_name,
                "balance": u.balance,
                "total_spent": u.total_spent,
                "is_banned": u.is_banned,
                "created_at": u.created_at.isoformat(),
            }
            for u in users
        ]
    }


@app.patch("/api/users/{user_id}")
async def api_update_user(user_id: int, data: dict, _=Depends(auth)):
    async with db.session() as s:
        result = await s.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(404, "User not found")
        if "balance" in data:
            user.balance = float(data["balance"])
        if "is_banned" in data:
            user.is_banned = bool(data["is_banned"])
        await s.commit()
    return {"ok": True}


@app.delete("/api/users/{user_id}")
async def api_delete_user(user_id: int, _=Depends(auth)):
    async with db.session() as s:
        await s.execute(delete(User).where(User.id == user_id))
        await s.commit()
    return {"ok": True}


# ── ACCOUNTS ──────────────────────────────────────────────────────────────────

@app.get("/api/accounts")
async def api_accounts(page: int = 0, limit: int = 20, status: str = "", tier: str = "", _=Depends(auth)):
    async with db.session() as s:
        q = select(TelegramAccount).order_by(TelegramAccount.added_at.desc())
        if status:
            q = q.where(TelegramAccount.status == status)
        if tier:
            q = q.where(TelegramAccount.tier == tier)
        total = (await s.execute(select(func.count()).select_from(q.subquery()))).scalar()
        result = await s.execute(q.offset(page * limit).limit(limit))
        accs = result.scalars().all()

    return {
        "total": total,
        "accounts": [
            {
                "id": a.id,
                "tier": a.tier,
                "phone_number": a.phone_number,
                "price": a.price,
                "status": a.status.value if hasattr(a.status, "value") else a.status,
                "country_code": a.country_code,
                "account_age_days": a.account_age_days,
                "has_2fa": a.has_2fa,
                "has_username": a.has_username,
                "description": a.description,
                "added_at": a.added_at.isoformat(),
                "sold_at": a.sold_at.isoformat() if a.sold_at else None,
            }
            for a in accs
        ]
    }


@app.post("/api/accounts")
async def api_add_account(data: dict, _=Depends(auth)):
    acc = await db.add_account(
        category=AccountCategory.FRAGMENT_VERIFIED,
        tier=data.get("tier", "standard"),
        phone_number=data["phone_number"],
        price=float(data["price"]),
        session_string=data.get("session_string"),
        tdata_path=data.get("tdata_path"),
        two_fa_password=data.get("two_fa_password"),
        email=data.get("email"),
        country_code=data.get("country_code"),
        account_age_days=data.get("account_age_days"),
        has_2fa=bool(data.get("two_fa_password")),
        has_username=bool(data.get("has_username", False)),
        description=data.get("description"),
    )
    return {"ok": True, "id": acc.id}


@app.patch("/api/accounts/{account_id}")
async def api_update_account(account_id: int, data: dict, _=Depends(auth)):
    async with db.session() as s:
        result = await s.execute(select(TelegramAccount).where(TelegramAccount.id == account_id))
        acc = result.scalar_one_or_none()
        if not acc:
            raise HTTPException(404, "Account not found")
        if "price" in data:
            acc.price = float(data["price"])
        if "status" in data:
            acc.status = data["status"]
        if "description" in data:
            acc.description = data["description"]
        if "tier" in data:
            acc.tier = data["tier"]
        await s.commit()
    return {"ok": True}


@app.delete("/api/accounts/{account_id}")
async def api_delete_account(account_id: int, _=Depends(auth)):
    async with db.session() as s:
        await s.execute(delete(TelegramAccount).where(TelegramAccount.id == account_id))
        await s.commit()
    return {"ok": True}


# ── ORDERS ────────────────────────────────────────────────────────────────────

@app.get("/api/orders")
async def api_orders(page: int = 0, limit: int = 20, status: str = "", _=Depends(auth)):
    async with db.session() as s:
        q = select(Order).order_by(Order.created_at.desc())
        if status:
            q = q.where(Order.status == status)
        total = (await s.execute(select(func.count()).select_from(q.subquery()))).scalar()
        result = await s.execute(q.offset(page * limit).limit(limit))
        orders = result.scalars().all()

    return {
        "total": total,
        "orders": [
            {
                "id": o.id,
                "user_id": o.user_id,
                "account_id": o.account_id,
                "payment_method": o.payment_method.value if hasattr(o.payment_method, "value") else o.payment_method,
                "payment_id": o.payment_id,
                "amount_usd": o.amount_usd,
                "status": o.status.value if hasattr(o.status, "value") else o.status,
                "created_at": o.created_at.isoformat(),
                "paid_at": o.paid_at.isoformat() if o.paid_at else None,
                "delivered_at": o.delivered_at.isoformat() if o.delivered_at else None,
            }
            for o in orders
        ]
    }


@app.patch("/api/orders/{order_id}")
async def api_update_order(order_id: int, data: dict, _=Depends(auth)):
    async with db.session() as s:
        result = await s.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(404)
        if "status" in data:
            order.status = data["status"]
        await s.commit()
    return {"ok": True}


# ── SERVE PANEL ───────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_panel(_=Depends(auth)):
    html_path = Path(__file__).parent / "panel.html"
    return HTMLResponse(content=html_path.read_text())


# ── OXAPAY WEBHOOK CALLBACK ───────────────────────────────────────────────────

@app.post("/oxapay/callback")
async def oxapay_callback(request: Request):
    """
    OxaPay sends a POST to this endpoint when a payment is confirmed.
    No auth required — OxaPay calls this from their servers.
    """
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"status": "error"}, status_code=400)

    track_id  = data.get("trackId", "")
    status    = data.get("status", "")
    order_id_str = data.get("orderId", "")

    if not track_id or not order_id_str:
        return JSONResponse({"status": "ignored"})

    # Only act on confirmed payments
    if status not in ("Paid", "Confirming"):
        return JSONResponse({"status": "ignored"})

    try:
        order_id = int(order_id_str)
    except ValueError:
        return JSONResponse({"status": "error"}, status_code=400)

    order = await db.get_order(order_id)
    if not order:
        return JSONResponse({"status": "not_found"}, status_code=404)

    # Already processed
    if order.status in (OrderStatus.DELIVERED, OrderStatus.PAID):
        return JSONResponse({"status": "already_processed"})

    # Mark paid
    await db.update_order_status(order_id, OrderStatus.PAID, payment_id=track_id)

    # Auto-deliver — notify the bot to send credentials to user
    # We do this by calling the bot's deliver function via shared DB state
    # The bot's payment handler polls for PAID orders and delivers them
    # Alternatively, trigger delivery directly here:
    try:
        from aiogram import Bot
        from payment import deliver_account

        bot = Bot(token=config.BOT_TOKEN, parse_mode="HTML")

        # Get user's telegram_id
        async with db.session() as s:
            from database.db import User
            result = await s.execute(
                select(User).where(User.id == order.user_id)
            )
            user = result.scalar_one_or_none()

        if user:
            await deliver_account(order_id, user.telegram_id, db, bot, config)
            await bot.session.close()

    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Delivery after callback failed: {e}")

    return JSONResponse({"status": "ok"})
