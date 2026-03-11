import asyncio
from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy import (
    Column, Integer, String, Float, Boolean,
    DateTime, Text, ForeignKey, Enum
)
import enum


class Base(DeclarativeBase):
    pass


class AccountStatus(str, enum.Enum):
    AVAILABLE = "available"
    SOLD = "sold"
    RESERVED = "reserved"


class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    PAID = "paid"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class PaymentMethod(str, enum.Enum):
    TON = "ton"
    OXAPAY = "oxapay"


class AccountCategory(str, enum.Enum):
    FRAGMENT_VERIFIED = "fragment_verified"


# Fragment account tiers/types for display
class FragmentTier(str, enum.Enum):
    STANDARD = "standard"       # Regular fragment verified
    AGED_30 = "aged_30"         # 30+ days old
    AGED_90 = "aged_90"         # 90+ days old
    PREMIUM = "premium"         # Premium + fragment verified


# ──────────────────────────────────────────────
# MODELS
# ──────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    username = Column(String(64), nullable=True)
    full_name = Column(String(128))
    balance = Column(Float, default=0.0)
    total_spent = Column(Float, default=0.0)
    is_banned = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class TelegramAccount(Base):
    __tablename__ = "telegram_accounts"
    id = Column(Integer, primary_key=True)
    category = Column(Enum(AccountCategory), nullable=False, default=AccountCategory.FRAGMENT_VERIFIED)
    tier = Column(String(32), nullable=False, default="standard")

    # Core account credentials (auto-delivered)
    phone_number = Column(String(20), nullable=False)   # Always required for Fragment accounts
    session_string = Column(Text, nullable=True)         # Pyrogram/Telethon session string
    tdata_path = Column(String(256), nullable=True)      # TData zip path/filename
    two_fa_password = Column(String(128), nullable=True) # 2FA password if set
    email = Column(String(128), nullable=True)           # Recovery email if any

    # Metadata
    description = Column(Text, nullable=True)
    country_code = Column(String(5), nullable=True)      # e.g. +44, +1, +7
    account_age_days = Column(Integer, nullable=True)    # Age in days at time of listing
    has_username = Column(Boolean, default=False)
    has_2fa = Column(Boolean, default=False)

    price = Column(Float, nullable=False)
    status = Column(Enum(AccountStatus), default=AccountStatus.AVAILABLE)
    added_at = Column(DateTime, default=datetime.utcnow)
    sold_at = Column(DateTime, nullable=True)
    extra_info = Column(Text, nullable=True)             # JSON for any extra metadata


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("telegram_accounts.id"), nullable=False)
    payment_method = Column(Enum(PaymentMethod))
    payment_id = Column(String(256), nullable=True)   # OxaPay or TON tx hash
    amount_usd = Column(Float, nullable=False)
    status = Column(Enum(OrderStatus), default=OrderStatus.PENDING)
    created_at = Column(DateTime, default=datetime.utcnow)
    paid_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)


class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String(16))
    tx_hash = Column(String(256), nullable=True)
    payment_method = Column(Enum(PaymentMethod))
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ──────────────────────────────────────────────
# DATABASE CLASS
# ──────────────────────────────────────────────

class Database:
    def __init__(self, url: str):
        self.engine = create_async_engine(url, echo=False)
        self.SessionLocal = sessionmaker(
            bind=self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def init(self):
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self):
        await self.engine.dispose()

    def session(self) -> AsyncSession:
        return self.SessionLocal()

    # ── Users ──
    async def get_or_create_user(self, telegram_id: int, username: str = None, full_name: str = None) -> User:
        from sqlalchemy import select
        async with self.session() as s:
            result = await s.execute(select(User).where(User.telegram_id == telegram_id))
            user = result.scalar_one_or_none()
            if not user:
                user = User(telegram_id=telegram_id, username=username, full_name=full_name)
                s.add(user)
                await s.commit()
                await s.refresh(user)
            return user

    async def get_user(self, telegram_id: int) -> User | None:
        from sqlalchemy import select
        async with self.session() as s:
            result = await s.execute(select(User).where(User.telegram_id == telegram_id))
            return result.scalar_one_or_none()

    # ── Accounts ──
    async def get_available_accounts(self, category: AccountCategory = None) -> list[TelegramAccount]:
        from sqlalchemy import select
        async with self.session() as s:
            q = select(TelegramAccount).where(TelegramAccount.status == AccountStatus.AVAILABLE)
            if category:
                q = q.where(TelegramAccount.category == category)
            result = await s.execute(q)
            return result.scalars().all()

    async def get_available_by_tier(self, tier: str) -> list:
        """Get available Fragment accounts filtered by tier."""
        from sqlalchemy import select
        async with self.session() as s:
            q = (
                select(TelegramAccount)
                .where(TelegramAccount.status == AccountStatus.AVAILABLE)
                .where(TelegramAccount.tier == tier)
                .order_by(TelegramAccount.price.asc())
            )
            result = await s.execute(q)
            return result.scalars().all()

    async def get_account(self, account_id: int) -> TelegramAccount | None:
        from sqlalchemy import select
        async with self.session() as s:
            result = await s.execute(select(TelegramAccount).where(TelegramAccount.id == account_id))
            return result.scalar_one_or_none()

    async def reserve_account(self, account_id: int):
        from sqlalchemy import select
        async with self.session() as s:
            result = await s.execute(select(TelegramAccount).where(TelegramAccount.id == account_id))
            acc = result.scalar_one_or_none()
            if acc:
                acc.status = AccountStatus.RESERVED
                await s.commit()

    async def mark_account_sold(self, account_id: int):
        from sqlalchemy import select
        async with self.session() as s:
            result = await s.execute(select(TelegramAccount).where(TelegramAccount.id == account_id))
            acc = result.scalar_one_or_none()
            if acc:
                acc.status = AccountStatus.SOLD
                acc.sold_at = datetime.utcnow()
                await s.commit()

    async def add_account(self, **kwargs) -> TelegramAccount:
        async with self.session() as s:
            acc = TelegramAccount(**kwargs)
            s.add(acc)
            await s.commit()
            await s.refresh(acc)
            return acc

    async def count_available(self, category: AccountCategory = None) -> int:
        from sqlalchemy import select, func
        async with self.session() as s:
            q = select(func.count()).select_from(TelegramAccount).where(
                TelegramAccount.status == AccountStatus.AVAILABLE
            )
            if category:
                q = q.where(TelegramAccount.category == category)
            result = await s.execute(q)
            return result.scalar()

    # ── Orders ──
    async def create_order(self, user_id: int, account_id: int, payment_method: PaymentMethod,
                            amount_usd: float) -> Order:
        async with self.session() as s:
            order = Order(
                user_id=user_id, account_id=account_id,
                payment_method=payment_method, amount_usd=amount_usd
            )
            s.add(order)
            await s.commit()
            await s.refresh(order)
            return order

    async def get_order(self, order_id: int) -> Order | None:
        from sqlalchemy import select
        async with self.session() as s:
            result = await s.execute(select(Order).where(Order.id == order_id))
            return result.scalar_one_or_none()

    async def update_order_status(self, order_id: int, status: OrderStatus,
                                   payment_id: str = None):
        from sqlalchemy import select
        async with self.session() as s:
            result = await s.execute(select(Order).where(Order.id == order_id))
            order = result.scalar_one_or_none()
            if order:
                order.status = status
                if payment_id:
                    order.payment_id = payment_id
                if status == OrderStatus.PAID:
                    order.paid_at = datetime.utcnow()
                if status == OrderStatus.DELIVERED:
                    order.delivered_at = datetime.utcnow()
                await s.commit()

    async def get_user_orders(self, user_id: int) -> list[Order]:
        from sqlalchemy import select
        async with self.session() as s:
            result = await s.execute(
                select(Order).where(Order.user_id == user_id).order_by(Order.created_at.desc())
            )
            return result.scalars().all()
