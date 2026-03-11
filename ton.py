import aiohttp
import logging
import time
import hashlib

logger = logging.getLogger(__name__)

TONCENTER_API = "https://toncenter.com/api/v2"


class TonPaymentClient:
    def __init__(self, wallet_address: str, api_key: str):
        self.wallet_address = wallet_address
        self.api_key = api_key

    def generate_payment_memo(self, order_id: int) -> str:
        """Generate a unique memo/comment for a TON transaction."""
        raw = f"IKYC-ORDER-{order_id}-{int(time.time())}"
        return hashlib.md5(raw.encode()).hexdigest()[:12].upper()

    def get_deeplink(self, amount_ton: float, memo: str) -> str:
        """Generate a TonKeeper deeplink for payment."""
        # TonKeeper deeplink format
        return (
            f"ton://transfer/{self.wallet_address}"
            f"?amount={int(amount_ton * 1e9)}"
            f"&text={memo}"
        )

    def get_tonkeeper_link(self, amount_ton: float, memo: str) -> str:
        """Generate TonKeeper universal link."""
        return (
            f"https://app.tonkeeper.com/transfer/{self.wallet_address}"
            f"?amount={int(amount_ton * 1e9)}&text={memo}"
        )

    async def get_transactions(self, limit: int = 20) -> list[dict]:
        """Fetch recent transactions to this wallet."""
        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    "address": self.wallet_address,
                    "limit": limit,
                    "api_key": self.api_key,
                }
                async with session.get(
                    f"{TONCENTER_API}/getTransactions",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    data = await resp.json()
                    if data.get("ok"):
                        return data.get("result", [])
                    return []
        except Exception as e:
            logger.error(f"TON get_transactions failed: {e}")
            return []

    async def verify_payment(self, memo: str, expected_ton: float, since_timestamp: int) -> dict | None:
        """
        Check if a transaction with given memo arrived after since_timestamp.
        Returns the tx dict if found, else None.
        """
        txs = await self.get_transactions(limit=50)
        for tx in txs:
            try:
                msg = tx.get("in_msg", {})
                comment = msg.get("message", "")
                tx_time = tx.get("utime", 0)
                amount_nano = int(msg.get("value", 0))
                amount_ton_received = amount_nano / 1e9

                if (
                    comment == memo
                    and tx_time >= since_timestamp
                    and amount_ton_received >= expected_ton * 0.97  # 3% tolerance
                ):
                    return tx
            except Exception:
                continue
        return None

    async def get_ton_price_usd(self) -> float | None:
        """Fetch current TON/USD price from CoinGecko."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.coingecko.com/api/v3/simple/price?ids=the-open-network&vs_currencies=usd",
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    data = await resp.json()
                    return data["the-open-network"]["usd"]
        except Exception as e:
            logger.error(f"TON price fetch failed: {e}")
            return None

    async def usd_to_ton(self, usd_amount: float) -> float | None:
        price = await self.get_ton_price_usd()
        if price:
            return round(usd_amount / price, 4)
        return None
