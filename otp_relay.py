"""
OTP Relay — logs into each sold account via Pyrogram,
listens for the login OTP message, and forwards it to the buyer.
"""
import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.handlers import MessageHandler

logger = logging.getLogger(__name__)

# phone -> pyrogram Client (kept alive to receive OTPs)
_active_clients: dict[str, Client] = {}


async def start_otp_listener(phone: str, session_string: str, bot, db, config):
    """
    Start a Pyrogram client for this account.
    When Telegram sends the OTP to this number, we catch it and forward to buyer.
    """
    if phone in _active_clients:
        return  # already listening

    try:
        client = Client(
            name=f"otp_{phone.replace('+', '')}",
            api_id=config.TELEGRAM_API_ID,
            api_hash=config.TELEGRAM_API_HASH,
            session_string=session_string,
            in_memory=True,
        )

        async def on_message(client, message):
            """Catch OTP messages from Telegram's service account (777000)"""
            if message.from_user and message.from_user.id == 777000:
                text = message.text or ""
                logger.info(f"OTP received for {phone}: {text[:30]}")

                # Find the waiting buyer
                otp_req = await db.get_active_otp_request(phone)
                if otp_req:
                    try:
                        await bot.send_message(
                            otp_req.buyer_tg_id,
                            f"📲 <b>Login Code Received!</b>\n\n"
                            f"Your OTP for <code>{phone}</code>:\n\n"
                            f"<b>{text}</b>\n\n"
                            f"⚠️ Enter this code on Telegram to complete login.\n"
                            f"Code expires in a few minutes!"
                        )
                        await db.complete_otp_request(otp_req.id)
                        logger.info(f"OTP forwarded to buyer {otp_req.buyer_tg_id}")
                    except Exception as e:
                        logger.error(f"Failed to forward OTP: {e}")

        client.add_handler(MessageHandler(on_message, filters.private))
        await client.start()
        _active_clients[phone] = client
        logger.info(f"OTP listener started for {phone}")

    except Exception as e:
        logger.error(f"Failed to start OTP listener for {phone}: {e}")


async def stop_otp_listener(phone: str):
    client = _active_clients.pop(phone, None)
    if client:
        try:
            await client.stop()
        except Exception:
            pass


async def stop_all():
    for phone, client in list(_active_clients.items()):
        try:
            await client.stop()
        except Exception:
            pass
    _active_clients.clear()
