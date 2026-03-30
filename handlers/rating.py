from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from database.engine import AsyncSessionFactory
from database.repositories import RatingRepo
from keyboards import rating_menu_keyboard

router = Router()

MEDAL = ["🥇", "🥈", "🥉"]


def get_medal(index: int) -> str:
    return MEDAL[index] if index < 3 else f"{index + 1}."


@router.message(F.text == "🏆 Reyting")
async def rating_menu(message: Message):
    await message.answer(
        "🏆 <b>REYTING</b>\n\n"
        "Qaysi ko'rsatkich bo'yicha reytingni ko'rmoqchisiz?",
        reply_markup=rating_menu_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "rating:power")
async def rating_power(callback: CallbackQuery):
    async with AsyncSessionFactory() as session:
        repo = RatingRepo(session)
        rows = await repo.get_power_ranking()

    lines = ["⚡ <b>UMUMIY KUCH REYTINGI</b>\n"]
    for i, row in enumerate(rows):
        power = row.total_soldiers + row.total_dragons * 200 + row.total_scorpions * 25
        lines.append(
            f"{get_medal(i)} <b>{row.name}</b>\n"
            f"   ⚡ {power:,} kuch  |  🗡️ {row.total_soldiers:,}  🐉 {row.total_dragons}  🏹 {row.total_scorpions}"
        )

    await callback.answer()
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=rating_menu_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "rating:soldiers")
async def rating_soldiers(callback: CallbackQuery):
    async with AsyncSessionFactory() as session:
        repo = RatingRepo(session)
        rows = await repo.get_soldiers_ranking()

    lines = ["🗡️ <b>ASKARLAR REYTINGI</b>\n"]
    for i, row in enumerate(rows):
        lines.append(
            f"{get_medal(i)} <b>{row.name}</b>\n"
            f"   🗡️ {row.total_soldiers:,} askar"
        )

    await callback.answer()
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=rating_menu_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "rating:gold")
async def rating_gold(callback: CallbackQuery):
    async with AsyncSessionFactory() as session:
        repo = RatingRepo(session)
        rows = await repo.get_gold_ranking()

    lines = ["💰 <b>OLTIN REYTINGI</b>\n"]
    for i, row in enumerate(rows):
        lines.append(
            f"{get_medal(i)} <b>{row.name}</b>\n"
            f"   💰 {row.treasury:,} oltin"
        )

    await callback.answer()
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=rating_menu_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "rating:dragons")
async def rating_dragons(callback: CallbackQuery):
    async with AsyncSessionFactory() as session:
        repo = RatingRepo(session)
        rows = await repo.get_dragons_ranking()

    lines = ["🐉 <b>JANGCHILAR (AJDARLAR) REYTINGI</b>\n"]
    for i, row in enumerate(rows):
        lines.append(
            f"{get_medal(i)} <b>{row.name}</b>\n"
            f"   🐉 {row.total_dragons} ajdar  |  🏹 {row.total_scorpions} skorpion"
        )

    await callback.answer()
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=rating_menu_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "rating:wins")
async def rating_wins(callback: CallbackQuery):
    async with AsyncSessionFactory() as session:
        repo = RatingRepo(session)
        rows = await repo.get_wins_ranking()

    lines = ["🏆 <b>JANGDA YUTGANI REYTINGI</b>\n"]
    for i, (house_name, wins) in enumerate(rows):
        lines.append(
            f"{get_medal(i)} <b>{house_name}</b>\n"
            f"   🏆 {wins} g'alaba"
        )

    await callback.answer()
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=rating_menu_keyboard(),
        parse_mode="HTML"
    )
