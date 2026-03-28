from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from database.engine import AsyncSessionFactory
from database.repositories import UserRepo


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

        async with AsyncSessionFactory() as session:
            user_repo = UserRepo(session)
            user = await user_repo.get_by_id(user_tg.id)

            # Admin tekshiruvi
            from config.settings import settings
            # Admin IDs ni .env dan olish mumkin yoki DB dan

            data["db_user"] = user
            data["session"] = session
            return await handler(event, data)
