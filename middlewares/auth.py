from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from database.engine import AsyncSessionFactory
from database.repositories import UserRepo, PrisonerRepo
from config.settings import settings


# Asir lordga ruxsat berilgan tugmalar / komandalar
_PRISONER_ALLOWED_TEXTS = {"📊 Profil", "/start", "/help"}
_PRISONER_ALLOWED_CALLBACKS = {
    # Tovon to'lash uchun yo'l — boshqa xonadon to'laydi, shuning uchun bloklanmaydi
    # Asir o'z profilini ko'ra oladi
}


class AuthMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any],
    ) -> Any:
        user_tg = event.from_user
        if not user_tg:
            return await handler(event, data)

        # Admin bo'lsa — hech qanday cheklovsiz o'tkazib yuborish
        if user_tg.id in settings.ADMIN_IDS:
            async with AsyncSessionFactory() as session:
                user_repo = UserRepo(session)
                user = await user_repo.get_by_id(user_tg.id)
                data["db_user"] = user
                data["session"] = session
                return await handler(event, data)

        async with AsyncSessionFactory() as session:
            user_repo     = UserRepo(session)
            prisoner_repo = PrisonerRepo(session)
            user = await user_repo.get_by_id(user_tg.id)

            # Asir lord tekshiruvi (faqat oddiy foydalanuvchilar uchun)
            if user:
                active_prisoner = await prisoner_repo.get_by_prisoner_user(user.id)
                if active_prisoner:
                    # Message bo'lsa — faqat ruxsat etilgan matnlarga yo'l qo'yish
                    if isinstance(event, Message):
                        if event.text not in _PRISONER_ALLOWED_TEXTS:
                            await event.answer(
                                "🔗 <b>Siz asirdasiz.</b>\n\n"
                                "Faqat profil ko'ra olasiz.\n"
                                "Ozod bo'lish uchun ittifoqchilaringizdan yordam so'rang.",
                                parse_mode="HTML"
                            )
                            return
                    # CallbackQuery bo'lsa — prisoner: prefiksli callbacklarga yo'l qo'yish
                    elif isinstance(event, CallbackQuery):
                        if not event.data.startswith("prisoner:"):
                            await event.answer(
                                "🔗 Asirdasiz — bu amalni bajara olmaysiz.",
                                show_alert=True
                            )
                            return

            data["db_user"] = user
            data["session"] = session
            return await handler(event, data)
                        
