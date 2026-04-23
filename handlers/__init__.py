from aiogram import Dispatcher
from handlers.start import router as start_router
from handlers.profile import router as profile_router
from handlers.market import router as market_router
from handlers.war import router as war_router
from handlers.bank import router as bank_router
from handlers.diplomacy import router as diplomacy_router
from handlers.chat import router as chat_router
from handlers.admin import router as admin_router
from handlers.chronicle import router as chronicle_router
from handlers.claim import router as claim_router
from handlers.rating import router as rating_router
from handlers.war_ally import router as war_ally_router
from handlers.subscription import router as subscription_router
from handlers.tournament import router as tournament_router
from handlers.prisoner import router as prisoner_router
from handlers.guide import router as guide_router
from handlers.knight import router as knight_router
from handlers.knight_market import router as knight_market_router
from handlers.territory import router as territory_router


def register_all_handlers(dp: Dispatcher):
    # Majburiy obuna handler'i — birinchi ro'yxatdan o'tkaziladi
    dp.include_router(subscription_router)
    dp.include_router(start_router)
    dp.include_router(profile_router)
    dp.include_router(market_router)
    dp.include_router(war_router)
    dp.include_router(bank_router)
    dp.include_router(diplomacy_router)
    dp.include_router(chat_router)
    dp.include_router(admin_router)
    dp.include_router(chronicle_router)
    dp.include_router(claim_router)
    dp.include_router(rating_router)
    dp.include_router(war_ally_router)
    dp.include_router(tournament_router)
    dp.include_router(prisoner_router)
    dp.include_router(guide_router)
    dp.include_router(knight_router)
    dp.include_router(knight_market_router)
    dp.include_router(territory_router)
