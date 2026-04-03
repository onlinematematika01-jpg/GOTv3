"""
Majburiy obuna middleware.
Foydalanuvchi REQUIRED_CHANNEL_ID kanaliga a'zo bo'lmasa,
har qanday xabar yoki callback so'rovida unga kanal havola qilinadi
va bot ishlashdan to'xtatiladi.
"""

from typing import Callable, Dict, Any, Awaitable

from aiogram import BaseMiddleware, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from config.settings import settings
from keyboards.keyboards import subscription_keyboard


class SubscriptionMiddleware(BaseMiddleware):
    """Majburiy obuna tekshiruvi (Message va CallbackQuery uchun)."""

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any],
    ) -> Any:
        channel_id = settings.REQUIRED_CHANNEL_ID
        if not channel_id:
            return await handler(event, data)

        user = event.from_user
        if not user:
            return await handler(event, data)

        # Admin uchun tekshiruvni o'tkazib yuborish
        if user.id in settings.ADMIN_IDS:
            return await handler(event, data)

        bot: Bot = data["bot"]

        is_member = await self._check_membership(bot, channel_id, user.id)
        if is_member:
            return await handler(event, data)

        await self._notify_user(event, bot, channel_id)
        return

    @staticmethod
    async def _check_membership(bot: Bot, channel_id: int, user_id: int) -> bool:
        try:
            member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            return member.status not in ("left", "kicked", "banned")
        except (TelegramForbiddenError, TelegramBadRequest):
            return True
        except Exception:
            return True

    @staticmethod
    async def _notify_user(
        event: Message | CallbackQuery,
        bot: Bot,
        channel_id: int,
    ) -> None:
        channel_link = settings.REQUIRED_CHANNEL_LINK
        if not channel_link:
            try:
                chat = await bot.get_chat(channel_id)
                channel_link = (
                    f"https://t.me/{chat.username}" if chat.username else "https://t.me/"
                )
            except Exception:
                channel_link = "https://t.me/"

        text = (
            "⚔️ <b>A'zolik talab etiladi!</b>\n\n"
            "Botdan foydalanish uchun avval quyidagi kanalga a'zo bo'lishingiz kerak.\n\n"
            "A'zo bo'lganingizdan so'ng istalgan xabar yuboring yoki /start bosing."
        )

        keyboard = subscription_keyboard(channel_link)

        if isinstance(event, Message):
            await event.answer(text, reply_markup=keyboard, parse_mode="HTML")
        elif isinstance(event, CallbackQuery):
            await event.answer("⚠️ Avval kanalga a'zo bo'ling!", show_alert=True)
            await event.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
