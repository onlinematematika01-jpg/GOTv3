from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from database.engine import AsyncSessionFactory
from database.models import Chronicle
from sqlalchemy import select, desc
from datetime import timezone, timedelta

router = Router()

TASHKENT = timedelta(hours=5)

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
            # UTC dan Toshkent vaqtiga o'tkazish (+5 soat)
            tashkent_time = r.created_at.replace(tzinfo=timezone.utc) + TASHKENT
            date_str = tashkent_time.strftime("%d.%m %H:%M")
            desc = r.description[:120] + "..." if len(r.description) > 120 else r.description
            text += f"[{date_str}] {desc}\n\n"

        await message.answer(text, parse_mode="HTML")
