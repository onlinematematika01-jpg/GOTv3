from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from database.engine import AsyncSessionFactory
from database.repositories import UserRepo, BotSettingsRepo
from config.settings import settings


# Pauza holatida ham ishlashi kerak bo'lgan callback prefikslari
_PAUSE_ALLOWED_CALLBACKS = {"admin:"}


async def _is_game_paused() -> tuple[bool, str]:
    """
    BotSettings dan o'yin pauza holatini o'qiydi.
    Qaytaradi: (paused: bool, reason: str)
    """
    async with AsyncSessionFactory() as session:
        cfg = BotSettingsRepo(session)
        paused = await cfg.get("game_paused") or "false"
        reason = await cfg.get("pause_reason") or "Texnik ishlar olib borilmoqda."
    return paused.strip().lower() == "true", reason


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

        # Admin bo'lsa — pauza va boshqa cheklovlardan o'tkazib yuborish
        if user_tg.id in settings.ADMIN_IDS:
            async with AsyncSessionFactory() as session:
                user_repo = UserRepo(session)
                user = await user_repo.get_by_id(user_tg.id)
                data["db_user"] = user
                data["session"] = session
                return await handler(event, data)

        # ── O'YIN PAUZA TEKSHIRUVI ──────────────────────────────────────
        paused, pause_reason = await _is_game_paused()
        if paused:
            if isinstance(event, Message):
                await event.answer(
                    f"⏸ <b>O'yin vaqtincha to'xtatilgan</b>\n\n"
                    f"{pause_reason}",
                    parse_mode="HTML"
                )
                return
            elif isinstance(event, CallbackQuery):
                cb_data = event.data or ""
                if not any(cb_data.startswith(p) for p in _PAUSE_ALLOWED_CALLBACKS):
                    await event.answer(
                        f"⏸ O'yin to'xtatilgan: {pause_reason}",
                        show_alert=True
                    )
                    return
        # ────────────────────────────────────────────────────────────────

        async with AsyncSessionFactory() as session:
            user_repo = UserRepo(session)
            user = await user_repo.get_by_id(user_tg.id)
            data["db_user"] = user
            data["session"] = session
            return await handler(event, data)
