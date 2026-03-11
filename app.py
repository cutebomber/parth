import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pathlib import Path
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import select, func, delete
import secrets

from db import Database, User, TelegramAccount, Order
from config import Config

app = FastAPI(docs_url=None, redoc_url=None)
config = Config()
db = Database(config.DATABASE_URL)
security = HTTPBasic()


@app.on_event("startup")
async def startup():
    await db.init()


def auth(credentials: HTTPBasicCredentials = Depends(security)):
    ok = (
        secrets.compare_digest(credentials.username, config.PANEL_USER) and
        secrets.compare_digest(credentials.password, config.PANEL_PASS)
    )
    if not ok:
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic"})
    return credentials.username


# ── Stats ─────────────────────────────────────

@app.get("/api/stats")
async def api_stats(_=Depends(auth)):
    async with db.session() as s:
        total_users    = (await s.execute(select(func.count()).select_from(User))).scalar()
        available      = (await s.execute(select(func.count()).select_from(TelegramAccount).where(TelegramAccount.status == "available"))).scalar()
        sold           = (await s.execute(select(func.count()).select_from(TelegramAccount).where(TelegramAccount.status == "sold"))).scalar()
        revenue        = (await s.execute(select(func.sum(Order.amount_usd)).where(Order.status == "delivered"))).scalar() or 0.0
        pending_orders = (await s.execute(select(func.count()).select_from(Order).where(Order.status == "pending"))).scalar()
        total_orders   = (await s.execute(select(func.count()).select_from(Order))).scalar()
        week_ago  = datetime.utcnow() - timedelta(days=7)
        month_ago = datetime.utcnow() - timedelta(days=30)
        revenue_7d  = (await s.execute(select(func.sum(Order.amount_usd)).where(Order.status == "delivered").where(Order.paid_at >= week_ago))).scalar() or 0.0
        revenue_30d = (await s.execute(select(func.sum(Order.amount_usd)).where(Order.status == "delivered").where(Order.paid_at >= month_ago))).scalar() or 0.0
        new_users   = (await s.execute(select(func.count()).select_from(User).where(User.created_at >= week_ago))).scalar()
    return {
        "total_users": total_users, "new_users_7d": new_users,
        "available": available, "sold": sold,
        "revenue_total": round(revenue, 2), "revenue_7d": round(revenue_7d, 2), "revenue_30d": round(revenue_30d, 2),
        "pending_orders": pending_orders, "total_orders": total_orders,
    }


# ── Users ─────────────────────────────────────

@app.get("/api/users")
async def api_users(page: int = 0, limit: int = 20, search: str = "", _=Depends(auth)):
    async with db.session() as s:
        q = select(User).order_by(User.created_at.desc())
        if search:
            q = q.where(User.username.ilike(f"%{search}%") | User.full_name.ilike(f"%{search}%"))
        total = (await s.execute(select(func.count()).select_from(q.subquery()))).scalar()
        users = (await s.execute(q.offset(page * limit).limit(limit))).scalars().all()
    return {"total": total, "users": [
        {"id": u.id, "telegram_id": u.telegram_id, "username": u.username,
         "full_name": u.full_name, "balance": u.balance, "total_spent": u.total_spent,
         "is_banned": u.is_banned, "created_at": u.created_at.isoformat()}
        for u in users
    ]}


@app.patch("/api/users/{user_id}")
async def api_update_user(user_id: int, data: dict, _=Depends(auth)):
    async with db.session() as s:
        r = await s.execute(select(User).where(User.id == user_id))
        user = r.scalar_one_or_none()
        if not user: raise HTTPException(404)
        if "balance"   in data: user.balance   = float(data["balance"])
        if "is_banned" in data: user.is_banned = bool(data["is_banned"])
        await s.commit()
    return {"ok": True}


@app.delete("/api/users/{user_id}")
async def api_delete_user(user_id: int, _=Depends(auth)):
    async with db.session() as s:
        await s.execute(delete(User).where(User.id == user_id))
        await s.commit()
    return {"ok": True}


# ── Accounts ──────────────────────────────────

@app.get("/api/accounts")
async def api_accounts(page: int = 0, limit: int = 20, status: str = "", _=Depends(auth)):
    async with db.session() as s:
        q = select(TelegramAccount).order_by(TelegramAccount.added_at.desc())
        if status: q = q.where(TelegramAccount.status == status)
        total = (await s.execute(select(func.count()).select_from(q.subquery()))).scalar()
        accs  = (await s.execute(q.offset(page * limit).limit(limit))).scalars().all()
    return {"total": total, "accounts": [
        {"id": a.id, "phone_number": a.phone_number,
         "has_session": bool(a.session_string),
         "has_2fa": bool(a.two_fa_password),
         "two_fa_password": a.two_fa_password,
         "price": a.price, "status": a.status,
         "description": a.description,
         "added_at": a.added_at.isoformat(),
         "sold_at": a.sold_at.isoformat() if a.sold_at else None}
        for a in accs
    ]}


@app.post("/api/accounts")
async def api_add_account(data: dict, _=Depends(auth)):
    acc = await db.add_account(
        phone_number=data["phone_number"],
        price=float(data["price"]),
        session_string=data.get("session_string") or None,
        two_fa_password=data.get("two_fa_password") or None,
        description=data.get("description") or None,
    )
    return {"ok": True, "id": acc.id}


@app.patch("/api/accounts/{account_id}")
async def api_update_account(account_id: int, data: dict, _=Depends(auth)):
    async with db.session() as s:
        r = await s.execute(select(TelegramAccount).where(TelegramAccount.id == account_id))
        acc = r.scalar_one_or_none()
        if not acc: raise HTTPException(404)
        for field in ("price", "status", "description", "two_fa_password", "session_string"):
            if field in data:
                setattr(acc, field, data[field] if data[field] != "" else None)
        if "price" in data: acc.price = float(data["price"])
        await s.commit()
    return {"ok": True}


@app.delete("/api/accounts/{account_id}")
async def api_delete_account(account_id: int, _=Depends(auth)):
    async with db.session() as s:
        await s.execute(delete(TelegramAccount).where(TelegramAccount.id == account_id))
        await s.commit()
    return {"ok": True}


# ── Orders ────────────────────────────────────

@app.get("/api/orders")
async def api_orders(page: int = 0, limit: int = 20, status: str = "", _=Depends(auth)):
    async with db.session() as s:
        q = select(Order).order_by(Order.created_at.desc())
        if status: q = q.where(Order.status == status)
        total  = (await s.execute(select(func.count()).select_from(q.subquery()))).scalar()
        orders = (await s.execute(q.offset(page * limit).limit(limit))).scalars().all()
    return {"total": total, "orders": [
        {"id": o.id, "user_id": o.user_id, "account_id": o.account_id,
         "payment_method": o.payment_method, "payment_id": o.payment_id,
         "amount_usd": o.amount_usd, "status": o.status,
         "created_at": o.created_at.isoformat(),
         "paid_at": o.paid_at.isoformat() if o.paid_at else None}
        for o in orders
    ]}


@app.patch("/api/orders/{order_id}")
async def api_update_order(order_id: int, data: dict, _=Depends(auth)):
    async with db.session() as s:
        r = await s.execute(select(Order).where(Order.id == order_id))
        order = r.scalar_one_or_none()
        if not order: raise HTTPException(404)
        if "status" in data: order.status = data["status"]
        await s.commit()
    return {"ok": True}


# ── OxaPay Webhook ────────────────────────────

@app.post("/oxapay/callback")
async def oxapay_callback(request: Request):
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"status": "error"}, status_code=400)
    track_id     = data.get("trackId", "")
    status       = data.get("status", "")
    order_id_str = data.get("orderId", "")
    if not track_id or not order_id_str or status not in ("Paid", "Confirming"):
        return JSONResponse({"status": "ignored"})
    try:
        order_id = int(order_id_str)
    except ValueError:
        return JSONResponse({"status": "error"}, status_code=400)
    order = await db.get_order(order_id)
    if not order or order.status in ("delivered", "paid"):
        return JSONResponse({"status": "already_processed"})
    await db.update_order_status(order_id, "paid", payment_id=track_id)
    try:
        from aiogram import Bot
        from aiogram.client.default import DefaultBotProperties
        from payment import deliver_account
        bot  = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
        user = await db.get_user_by_id(order.user_id)
        if user:
            await deliver_account(order_id, user.telegram_id, db, bot, config)
        await bot.session.close()
    except Exception as e:
        import logging; logging.getLogger(__name__).error(f"Delivery error: {e}")
    return JSONResponse({"status": "ok"})


# ── Serve Panel ───────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_panel(_=Depends(auth)):
    return HTMLResponse(content=Path("panel.html").read_text())
