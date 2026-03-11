from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, Enum
import enum


class Base(DeclarativeBase):
    pass


class AccountStatus(str, enum.Enum):
    AVAILABLE = "available"
    SOLD      = "sold"
    RESERVED  = "reserved"


class OrderStatus(str, enum.Enum):
    PENDING   = "pending"
    PAID      = "paid"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED  = "refunded"


class PaymentMethod(str, enum.Enum):
    TON    = "ton"
    OXAPAY = "oxapay"


# ── Models ────────────────────────────────────

class User(Base):
    __tablename__ = "users"
    id          = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    username    = Column(String(64), nullable=True)
    full_name   = Column(String(128))
    balance     = Column(Float, default=0.0)
    total_spent = Column(Float, default=0.0)
    is_banned   = Column(Boolean, default=False)
    created_at  = Column(DateTime, default=datetime.utcnow)


class TelegramAccount(Base):
    __tablename__ = "telegram_accounts"
    id             = Column(Integer, primary_key=True)
    phone_number   = Column(String(20), nullable=False)
    session_string = Column(Text, nullable=True)      # Pyrogram session — used to receive OTP
    two_fa_password= Column(String(128), nullable=True)
    price          = Column(Float, nullable=False)
    status         = Column(String(16), default="available")
    description    = Column(Text, nullable=True)
    added_at       = Column(DateTime, default=datetime.utcnow)
    sold_at        = Column(DateTime, nullable=True)


class Order(Base):
    __tablename__ = "orders"
    id             = Column(Integer, primary_key=True)
    user_id        = Column(Integer, ForeignKey("users.id"), nullable=False)
    account_id     = Column(Integer, ForeignKey("telegram_accounts.id"), nullable=False)
    payment_method = Column(String(16))
    payment_id     = Column(String(256), nullable=True)
    amount_usd     = Column(Float, nullable=False)
    status         = Column(String(16), default="pending")
    created_at     = Column(DateTime, default=datetime.utcnow)
    paid_at        = Column(DateTime, nullable=True)
    delivered_at   = Column(DateTime, nullable=True)


class OtpRequest(Base):
    """Tracks active OTP relay sessions — buyer waiting for OTP"""
    __tablename__ = "otp_requests"
    id          = Column(Integer, primary_key=True)
    order_id    = Column(Integer, ForeignKey("orders.id"), nullable=False)
    buyer_tg_id = Column(Integer, nullable=False)   # buyer's telegram ID
    account_id  = Column(Integer, ForeignKey("telegram_accounts.id"), nullable=False)
    phone       = Column(String(20), nullable=False)
    status      = Column(String(16), default="waiting")  # waiting / sent / done
    created_at  = Column(DateTime, default=datetime.utcnow)


# ── Database class ────────────────────────────

class Database:
    def __init__(self, url: str):
        self.engine = create_async_engine(url, echo=False)
        self.SessionLocal = sessionmaker(bind=self.engine, class_=AsyncSession, expire_on_commit=False)

    async def init(self):
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self):
        await self.engine.dispose()

    def session(self) -> AsyncSession:
        return self.SessionLocal()

    # ── Users ──
    async def get_or_create_user(self, telegram_id, username=None, full_name=None):
        from sqlalchemy import select
        async with self.session() as s:
            r = await s.execute(select(User).where(User.telegram_id == telegram_id))
            user = r.scalar_one_or_none()
            if not user:
                user = User(telegram_id=telegram_id, username=username, full_name=full_name)
                s.add(user)
                await s.commit()
                await s.refresh(user)
            return user

    async def get_user(self, telegram_id):
        from sqlalchemy import select
        async with self.session() as s:
            r = await s.execute(select(User).where(User.telegram_id == telegram_id))
            return r.scalar_one_or_none()

    async def get_user_by_id(self, user_id):
        from sqlalchemy import select
        async with self.session() as s:
            r = await s.execute(select(User).where(User.id == user_id))
            return r.scalar_one_or_none()

    # ── Accounts ──
    async def get_available_accounts(self):
        from sqlalchemy import select
        async with self.session() as s:
            r = await s.execute(
                select(TelegramAccount)
                .where(TelegramAccount.status == "available")
                .order_by(TelegramAccount.price.asc())
            )
            return r.scalars().all()

    async def get_account(self, account_id):
        from sqlalchemy import select
        async with self.session() as s:
            r = await s.execute(select(TelegramAccount).where(TelegramAccount.id == account_id))
            return r.scalar_one_or_none()

    async def add_account(self, **kwargs):
        async with self.session() as s:
            acc = TelegramAccount(**kwargs)
            s.add(acc)
            await s.commit()
            await s.refresh(acc)
            return acc

    async def reserve_account(self, account_id):
        from sqlalchemy import select
        async with self.session() as s:
            r = await s.execute(select(TelegramAccount).where(TelegramAccount.id == account_id))
            acc = r.scalar_one_or_none()
            if acc:
                acc.status = "reserved"
                await s.commit()

    async def mark_account_sold(self, account_id):
        from sqlalchemy import select
        async with self.session() as s:
            r = await s.execute(select(TelegramAccount).where(TelegramAccount.id == account_id))
            acc = r.scalar_one_or_none()
            if acc:
                acc.status = "sold"
                acc.sold_at = datetime.utcnow()
                await s.commit()

    async def update_account(self, account_id, **kwargs):
        from sqlalchemy import select
        async with self.session() as s:
            r = await s.execute(select(TelegramAccount).where(TelegramAccount.id == account_id))
            acc = r.scalar_one_or_none()
            if acc:
                for k, v in kwargs.items():
                    setattr(acc, k, v)
                await s.commit()

    # ── Orders ──
    async def create_order(self, user_id, account_id, payment_method, amount_usd):
        async with self.session() as s:
            order = Order(user_id=user_id, account_id=account_id,
                          payment_method=payment_method, amount_usd=amount_usd)
            s.add(order)
            await s.commit()
            await s.refresh(order)
            return order

    async def get_order(self, order_id):
        from sqlalchemy import select
        async with self.session() as s:
            r = await s.execute(select(Order).where(Order.id == order_id))
            return r.scalar_one_or_none()

    async def update_order_status(self, order_id, status, payment_id=None):
        from sqlalchemy import select
        async with self.session() as s:
            r = await s.execute(select(Order).where(Order.id == order_id))
            order = r.scalar_one_or_none()
            if order:
                order.status = status
                if payment_id:
                    order.payment_id = payment_id
                if status == "paid":
                    order.paid_at = datetime.utcnow()
                if status == "delivered":
                    order.delivered_at = datetime.utcnow()
                await s.commit()

    async def get_user_orders(self, user_id):
        from sqlalchemy import select
        async with self.session() as s:
            r = await s.execute(
                select(Order).where(Order.user_id == user_id)
                .order_by(Order.created_at.desc())
            )
            return r.scalars().all()

    # ── OTP Requests ──
    async def create_otp_request(self, order_id, buyer_tg_id, account_id, phone):
        async with self.session() as s:
            req = OtpRequest(order_id=order_id, buyer_tg_id=buyer_tg_id,
                             account_id=account_id, phone=phone)
            s.add(req)
            await s.commit()
            await s.refresh(req)
            return req

    async def get_active_otp_request(self, phone):
        from sqlalchemy import select
        async with self.session() as s:
            r = await s.execute(
                select(OtpRequest)
                .where(OtpRequest.phone == phone)
                .where(OtpRequest.status == "waiting")
                .order_by(OtpRequest.created_at.desc())
            )
            return r.scalars().first()

    async def complete_otp_request(self, otp_request_id):
        from sqlalchemy import select
        async with self.session() as s:
            r = await s.execute(select(OtpRequest).where(OtpRequest.id == otp_request_id))
            req = r.scalar_one_or_none()
            if req:
                req.status = "done"
                await s.commit()
