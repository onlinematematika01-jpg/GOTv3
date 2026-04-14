import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config.settings import settings
from database.engine import create_tables
from handlers import register_all_handlers
from middlewares.auth import AuthMiddleware
from middlewares.logging import LoggingMiddleware
from middlewares.subscription import SubscriptionMiddleware
from utils.scheduler import setup_scheduler, set_global_scheduler, set_global_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Global scheduler — reload_farm_jobs uchun
scheduler = AsyncIOScheduler()


async def main():
    bot = Bot(token=settings.BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Middlewares (tartib muhim: avval Subscription, so'ng Auth)
    dp.message.middleware(LoggingMiddleware())
    dp.message.middleware(SubscriptionMiddleware())   # ← yangi
    dp.message.middleware(AuthMiddleware())
    dp.callback_query.middleware(SubscriptionMiddleware())  # ← yangi
    dp.callback_query.middleware(AuthMiddleware())

    # Register all handlers
    register_all_handlers(dp)

    # Create DB tables
    await create_tables()

    # Scheduler
    set_global_scheduler(scheduler)
    set_global_bot(bot)
    await setup_scheduler(scheduler, bot)
    scheduler.start()

    logger.info("Game of Thrones Bot V3 ishga tushdi!")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
