import aiohttp
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

OXAPAY_BASE = "https://api.oxapay.com"


@dataclass
class PaymentInvoice:
    invoice_id: str
    pay_link: str
    amount: float
    currency: str
    status: str


class OxaPayClient:
    def __init__(self, api_key: str, merchant_key: str):
        self.api_key = api_key
        self.merchant_key = merchant_key

    async def create_invoice(
        self,
        amount: float,
        currency: str = "USDT",
        order_id: str = "",
        description: str = "Telegram Account Purchase",
        callback_url: str = "",
        return_url: str = "",
    ) -> PaymentInvoice | None:
        """Create a payment invoice via OxaPay."""
        payload = {
            "merchant": self.merchant_key,
            "amount": amount,
            "currency": currency,
            "lifeTime": 30,  # minutes
            "feePaidByPayer": 1,
            "underPaidCover": 2.5,
            "callbackUrl": callback_url,
            "returnUrl": return_url,
            "description": description,
            "orderId": order_id,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{OXAPAY_BASE}/merchants/request",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    data = await resp.json()
                    if data.get("result") == 100:
                        return PaymentInvoice(
                            invoice_id=data["trackId"],
                            pay_link=data["payLink"],
                            amount=amount,
                            currency=currency,
                            status="pending"
                        )
                    else:
                        logger.error(f"OxaPay error: {data}")
                        return None
        except Exception as e:
            logger.error(f"OxaPay create_invoice failed: {e}")
            return None

    async def check_payment(self, track_id: str) -> dict | None:
        """Check payment status by trackId."""
        payload = {
            "merchant": self.merchant_key,
            "trackId": track_id,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{OXAPAY_BASE}/merchants/inquiry",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    return await resp.json()
        except Exception as e:
            logger.error(f"OxaPay check_payment failed: {e}")
            return None

    def verify_callback(self, data: dict) -> bool:
        """Verify OxaPay webhook callback (basic check)."""
        return data.get("merchant") == self.merchant_key

    @staticmethod
    def is_paid(status_data: dict) -> bool:
        """Returns True if payment is confirmed paid."""
        return status_data.get("status") in ("Paid", "Confirming")
