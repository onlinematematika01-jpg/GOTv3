from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database.engine import AsyncSessionFactory
from database.repositories import UserRepo
from database.models import InternalMessage
from sqlalchemy import select, desc

router = Router()


class ChatState(StatesGroup):
    writing_message = State()


@router.message(F.text == "💬 Ichki Chat")
async def chat_menu(message: Message, state: FSMContext):
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        user = await user_repo.get_by_id(message.from_user.id)

        if not user or not user.house_id:
            await message.answer("❌ Xonadoningiz yo'q.")
            return

        # So'nggi 10 ta xabar
        result = await session.execute(
            select(InternalMessage)
            .where(InternalMessage.house_id == user.house_id)
            .order_by(desc(InternalMessage.created_at))
            .limit(10)
        )
        messages = result.scalars().all()
        messages.reverse()

        if messages:
            chat_text = "💬 <b>Xonadon Ichki Chat (so'nggi xabarlar):</b>\n\n"
            for msg in messages:
                sender = await user_repo.get_by_id(msg.sender_id)
                sender_name = sender.full_name if sender else "Noma'lum"
                time_str = msg.created_at.strftime("%H:%M")
                chat_text += f"[{time_str}] <b>{sender_name}:</b> {msg.content}\n"
        else:
            chat_text = "💬 <b>Ichki Chat</b>\n\nHali xabarlar yo'q. Birinchi bo'ling!"

        chat_text += "\n\n✏️ Xabar yozing (pastga yuboring):"
        await state.set_state(ChatState.writing_message)
        await message.answer(chat_text, parse_mode="HTML")


@router.message(ChatState.writing_message)
async def send_internal_message(message: Message, state: FSMContext):
    if not message.text or message.text.startswith("/") or len(message.text) > 500:
        await message.answer("❌ Xabar 1–500 belgi bo'lishi kerak.")
        return

    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        user = await user_repo.get_by_id(message.from_user.id)

        if not user or not user.house_id:
            await state.clear()
            return

        # Xabarni saqlash
        msg = InternalMessage(
            sender_id=user.id,
            house_id=user.house_id,
            content=message.text,
        )
        session.add(msg)
        await session.commit()

        # Barcha xonadon a'zolariga yuborish
        members = await user_repo.get_house_members(user.house_id)
        notification = (
            f"💬 <b>{user.full_name}:</b> {message.text}"
        )
        for member in members:
            if member.id != user.id:
                try:
                    await message.bot.send_message(
                        member.id,
                        notification,
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

    await message.answer("✅ Xabar yuborildi.")
    await state.clear()
