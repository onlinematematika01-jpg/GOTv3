from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from database.engine import AsyncSessionFactory
from database.models import Chronicle
from sqlalchemy import select, desc

router = Router()


@router.message(F.text == "📜 Xronika")
@router.message(Command("chronicle"))
async def show_chronicle(message: Message):
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Chronicle)
            .order_by(desc(Chronicle.created_at))
            .limit(15)
        )
        records = result.scalars().all()

        if not records:
            await message.answer("📜 Xronika hali bo'sh. Birinchi voqea siz bo'ling!")
            return

        text = "📜 <b>YETTI QIROLLIK XRONIKASI</b>\n\n"
        for r in records:
            date_str = r.created_at.strftime("%d.%m %H:%M")
            text += f"[{date_str}] {r.description[:120]}...\n\n" if len(r.description) > 120 else f"[{date_str}] {r.description}\n\n"

        await message.answer(text, parse_mode="HTML")
