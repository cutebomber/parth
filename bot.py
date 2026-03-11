import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from config import Config
from database.db import Database
from handlers import start, shop, payment, admin
from payments.oxapay import OxaPayClient
from payments.ton import TonPaymentClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def set_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="🏠 Main menu"),
        BotCommand(command="shop", description="🛒 Browse accounts"),
        BotCommand(command="orders", description="📦 My orders"),
        BotCommand(command="balance", description="💰 My balance"),
        BotCommand(command="support", description="🆘 Support"),
    ]
    await bot.set_my_commands(commands)


async def main():
    config = Config()
    db = Database(config.DATABASE_URL)
    await db.init()

    oxapay = OxaPayClient(config.OXAPAY_API_KEY, config.OXAPAY_MERCHANT)
    ton_client = TonPaymentClient(config.TON_WALLET_ADDRESS, config.TON_API_KEY)

    bot = Bot(token=config.BOT_TOKEN, parse_mode="HTML")
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Pass shared dependencies to handlers via middleware data
    dp["db"] = db
    dp["config"] = config
    dp["oxapay"] = oxapay
    dp["ton_client"] = ton_client

    # Register routers
    dp.include_router(start.router)
    dp.include_router(shop.router)
    dp.include_router(payment.router)
    dp.include_router(admin.router)

    await set_commands(bot)
    logger.info("🤖 @ikycbot is starting...")

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
