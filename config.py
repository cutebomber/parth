from dataclasses import dataclass, field


@dataclass
class Config:
    # ─── Telegram Bot ───────────────────────────────
    BOT_TOKEN: str = "8583077890:AAGu7OE_g1ginrWM2p9ysNuL6oZXYfKJtDY"
    ADMIN_IDS: list = field(default_factory=lambda: [1899208318])  # Add your Telegram user IDs

    # ─── Database ────────────────────────────────────
    DATABASE_URL: str = "sqlite+aiosqlite:///ikycbot.db"
    # For PostgreSQL: "postgresql+asyncpg://user:pass@localhost/ikycbot"

    # ─── OxaPay ──────────────────────────────────────
    OXAPAY_API_KEY: str = "1IK3BB-CSHDPY-4VRFWG-JMANBL"
    OXAPAY_MERCHANT: str = "P5JRXH-BGKQTO-TID5OG-OATXBQ"
    OXAPAY_CALLBACK_URL: str = "https://http://192.3.187.66:8080/oxapay/callback"

    # ─── TON / TonKeeper ─────────────────────────────
    TON_WALLET_ADDRESS: str = "UQAsuaEdtH11k4CRMUv4lNlJWy2obQo-QqcuQmv7cSyu2DuL"
    TON_API_KEY: str = "640b4486094ffd81a5e49a4bb7c599fb55e8bfa3d391f140fb02b12b10c032ca"

    # ─── Bot Settings ────────────────────────────────
    SUPPORT_USERNAME: str = "@hankie"
    CHANNEL_ID: str = "-1003816632858"

    # ─── Web Admin Panel ─────────────────────────────
    PANEL_USER: str = "admin"
    PANEL_PASS: str = "overpower"
    PANEL_PORT: int = 8080
