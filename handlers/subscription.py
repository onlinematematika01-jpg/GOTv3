"""
Foydalanuvchi "A'zo bo'ldim, tekshirish" tugmasini bosganda
a'zolikni qayta tekshiradi va natijani bildiradi.
"""

from aiogram import Router, Bot, F
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from config.settings import settings

router = Router()


@router.callback_query(F.data == "check_subscription")
async def check_subscription_callback(callback: CallbackQuery, bot: Bot):
    """Foydalanuvchi tugmani bosganda a'zolikni qayta tekshiradi."""
    channel_id = settings.REQUIRED_CHANNEL_ID

    # Kanal sozlanmagan bo'lsa — o'tkazib yuborish
    if not channel_id:
        await callback.answer("✅ Tekshiruv talab etilmaydi.", show_alert=False)
        return

    try:
        member = await bot.get_chat_member(
            chat_id=channel_id, user_id=callback.from_user.id
        )
        is_member = member.status not in ("left", "kicked", "banned")
    except (TelegramForbiddenError, TelegramBadRequest):
        is_member = True
    except Exception:
        is_member = True

    if is_member:
        await callback.answer(
            "✅ A'zolik tasdiqlandi! Endi botdan foydalanishingiz mumkin.",
            show_alert=True,
        )
        # Xabarni o'chirish (foydalanuvchi interfeysini tozalash)
        try:
            await callback.message.delete()
        except Exception:
            pass
    else:
        await callback.answer(
            "❌ Siz hali kanalga a'zo bo'lmagansiz. "
            "Iltimos, kanalga o'ting va a'zo bo'ling.",
            show_alert=True,
        )
