from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from database.engine import AsyncSessionFactory
from database.repositories import RatingRepo, CustomItemRepo
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

        # Har xonadon uchun custom item kuchlarini hisoblash
        item_repo = CustomItemRepo(session)
        house_item_power: dict[int, dict] = {}
        for row in rows:
            items = await item_repo.get_house_items_with_info(row.id)
            extra_attack = sum(r.item.attack_power * r.quantity for r in items)
            extra_defense = sum(r.item.defense_power * r.quantity for r in items)
            house_item_power[row.id] = {"attack": extra_attack, "defense": extra_defense, "items": items}

    lines = ["⚡ <b>UMUMIY KUCH REYTINGI</b>\n"]
    house_powers = []
    for row in rows:
        base_power = row.total_soldiers + row.total_dragons * 200 + row.total_scorpions * 25
        item_atk = house_item_power[row.id]["attack"]
        item_def = house_item_power[row.id]["defense"]
        total_power = base_power + item_atk + item_def
        house_powers.append((row, total_power, item_atk, item_def, house_item_power[row.id]["items"]))

    # Umumiy kuch bo'yicha qayta tartiblash
    house_powers.sort(key=lambda x: x[1], reverse=True)

    for i, (row, total_power, item_atk, item_def, items) in enumerate(house_powers):
        item_line = ""
        if items:
            item_parts = [f"{r.item.emoji}{r.item.name}×{r.quantity}" for r in items]
            item_line = f"\n   🎯 Itemlar: {', '.join(item_parts)}"
            if item_atk > 0 or item_def > 0:
                item_line += f" (+{item_atk}⚔️ +{item_def}🛡)"
        lines.append(
            f"{get_medal(i)} <b>{row.name}</b>\n"
            f"   ⚡ {total_power:,} kuch  |  🗡️ {row.total_soldiers:,}  🐉 {row.total_dragons}  🏹 {row.total_scorpions}"
            + item_line
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
