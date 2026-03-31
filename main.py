import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config.settings import settings
from database.engine import create_tables
from utils.scheduler import setup_static_jobs, reload_farm_schedules

# Handlers
from handlers import (
    start, profile, market, bank,
    war, war_ally, diplomacy, claim,
    rating, chat, chronicle, admin,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Global scheduler (admin.py dan import qilinadi) ───────────────────────────
scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")


async def on_startup(bot: Bot):
    """Bot ishga tushganda bajariladigan amallar."""
    # 1. DB jadvallarini yaratish (agar mavjud bo'lmasa)
    await create_tables()
    logger.info("DB jadvallari tayyor.")

    # 2. Statik scheduler job'larini qo'shish (urush, bank, tribute, va h.k.)
    setup_static_jobs(scheduler)

    # 3. Farm jadvallarini DB dan yuklash va scheduler'ga qo'shish
    await reload_farm_schedules(scheduler)

    # 4. Schedulerni ishga tushirish
    scheduler.start()
    logger.info("Scheduler ishga tushdi.")

    logger.info("Bot muvaffaqiyatli ishga tushdi! 🐺")


async def on_shutdown(bot: Bot):
    """Bot to'xtatilganda bajariladigan amallar."""
    scheduler.shutdown(wait=False)
    logger.info("Scheduler to'xtatildi.")


async def main():
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher()

    # Startup / shutdown hooks
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Handlerlarni ro'yxatdan o'tkazish
    dp.include_router(admin.router)
    dp.include_router(start.router)
    dp.include_router(profile.router)
    dp.include_router(market.router)
    dp.include_router(bank.router)
    dp.include_router(war.router)
    dp.include_router(war_ally.router)
    dp.include_router(diplomacy.router)
    dp.include_router(claim.router)
    dp.include_router(rating.router)
    dp.include_router(chat.router)
    dp.include_router(chronicle.router)

    logger.info("Polling boshlandi...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
