from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database.engine import AsyncSessionFactory
from database.repositories import RatingRepo, CustomItemRepo, AllianceGroupRepo
from keyboards import rating_menu_keyboard

router = Router()

MEDAL = ["🥇", "🥈", "🥉"]
PAGE_SIZE = 10


def get_medal(index: int) -> str:
    return MEDAL[index] if index < 3 else f"{index + 1}."


def pagination_keyboard(rating_type: str, page: int, total: int) -> InlineKeyboardMarkup:
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    builder = InlineKeyboardBuilder()
    if page > 0:
        builder.button(text="◀️ Oldingi", callback_data=f"rating_page:{rating_type}:{page - 1}")
    builder.button(text=f"📄 {page + 1}/{total_pages}", callback_data="rating_page:noop:0")
    if page < total_pages - 1:
        builder.button(text="Keyingi ▶️", callback_data=f"rating_page:{rating_type}:{page + 1}")
    builder.adjust(3)
    builder.row(InlineKeyboardButton(text="🔙 Reyting menyusi", callback_data="rating:menu"))
    return builder.as_markup()


async def _get_power_data(session) -> list:
    repo = RatingRepo(session)
    rows = await repo.get_power_ranking(limit=1000)
    item_repo = CustomItemRepo(session)
    result = []
    for row in rows:
        items = await item_repo.get_house_items_with_info(row.id)
        extra_atk = sum(r.item.attack_power * r.quantity for r in items)
        extra_def = sum(r.item.defense_power * r.quantity for r in items)
        base = row.total_soldiers + row.total_dragons * 200 + row.total_scorpions * 25
        result.append((row, base + extra_atk + extra_def, extra_atk, extra_def, items))
    result.sort(key=lambda x: x[1], reverse=True)
    return result


async def _get_soldiers_data(session) -> list:
    return await RatingRepo(session).get_soldiers_ranking(limit=1000)


async def _get_gold_data(session) -> list:
    return await RatingRepo(session).get_gold_ranking(limit=1000)


async def _get_dragons_data(session) -> list:
    return await RatingRepo(session).get_dragons_ranking(limit=1000)


async def _get_wins_data(session) -> list:
    return await RatingRepo(session).get_wins_ranking(limit=1000)


async def _get_alliances_data(session) -> list:
    return await AllianceGroupRepo(session).get_alliance_power_ranking(limit=1000)


def _build_power_page(data: list, page: int) -> str:
    start = page * PAGE_SIZE
    lines = ["⚡ <b>UMUMIY KUCH REYTINGI</b>\n"]
    for i, (row, total_power, item_atk, item_def, items) in enumerate(data[start: start + PAGE_SIZE]):
        rank = start + i
        item_line = ""
        if items:
            parts = [f"{r.item.emoji}{r.item.name}×{r.quantity}" for r in items]
            item_line = f"\n   🎯 {', '.join(parts)}"
            if item_atk > 0 or item_def > 0:
                item_line += f" (+{item_atk}⚔️ +{item_def}🛡)"
        lines.append(
            f"{get_medal(rank)} <b>{row.name}</b>\n"
            f"   ⚡ {total_power:,}  |  🗡️ {row.total_soldiers:,}  🐉 {row.total_dragons}  🏹 {row.total_scorpions}"
            + item_line
        )
    return "\n".join(lines)


def _build_soldiers_page(data: list, page: int) -> str:
    start = page * PAGE_SIZE
    lines = ["🗡️ <b>ASKARLAR REYTINGI</b>\n"]
    for i, row in enumerate(data[start: start + PAGE_SIZE]):
        lines.append(f"{get_medal(start + i)} <b>{row.name}</b>\n   🗡️ {row.total_soldiers:,} askar")
    return "\n".join(lines)


def _build_gold_page(data: list, page: int) -> str:
    start = page * PAGE_SIZE
    lines = ["💰 <b>OLTIN REYTINGI</b>\n"]
    for i, row in enumerate(data[start: start + PAGE_SIZE]):
        lines.append(f"{get_medal(start + i)} <b>{row.name}</b>\n   💰 {row.treasury:,} oltin")
    return "\n".join(lines)


def _build_dragons_page(data: list, page: int) -> str:
    start = page * PAGE_SIZE
    lines = ["🐉 <b>JANGCHILAR REYTINGI</b>\n"]
    for i, row in enumerate(data[start: start + PAGE_SIZE]):
        lines.append(
            f"{get_medal(start + i)} <b>{row.name}</b>\n"
            f"   🐉 {row.total_dragons} ajdar  |  🏹 {row.total_scorpions} skorpion"
        )
    return "\n".join(lines)


def _build_wins_page(data: list, page: int) -> str:
    start = page * PAGE_SIZE
    lines = ["🏆 <b>JANGDA YUTGANI REYTINGI</b>\n"]
    for i, (house_name, wins) in enumerate(data[start: start + PAGE_SIZE]):
        lines.append(f"{get_medal(start + i)} <b>{house_name}</b>\n   🏆 {wins} g'alaba")
    return "\n".join(lines)


def _build_alliances_page(data: list, page: int) -> str:
    start = page * PAGE_SIZE
    lines = ["⚔️ <b>KUCHLI ITTIFOQLAR REYTINGI</b>\n"]
    for i, entry in enumerate(data[start: start + PAGE_SIZE]):
        group = entry["group"]
        member_names = " · ".join(entry["member_names"])
        lines.append(
            f"{get_medal(start + i)} <b>{group.name}</b>\n"
            f"   ⚡ {entry['power']:,} kuch  |  👥 {entry['member_count']} xonadon\n"
            f"   🗡️ {entry['total_soldiers']:,}  🐉 {entry['total_dragons']}  🏹 {entry['total_scorpions']}\n"
            f"   <i>{member_names}</i>"
        )
    return "\n".join(lines)


RATING_HANDLERS = {
    "power":     (_get_power_data,     _build_power_page),
    "soldiers":  (_get_soldiers_data,  _build_soldiers_page),
    "gold":      (_get_gold_data,      _build_gold_page),
    "dragons":   (_get_dragons_data,   _build_dragons_page),
    "wins":      (_get_wins_data,      _build_wins_page),
    "alliances": (_get_alliances_data, _build_alliances_page),
}


async def _show_rating(callback: CallbackQuery, rating_type: str, page: int = 0):
    if rating_type not in RATING_HANDLERS:
        await callback.answer("Noto'g'ri reyting turi!", show_alert=True)
        return
    get_data, build_page = RATING_HANDLERS[rating_type]
    async with AsyncSessionFactory() as session:
        data = await get_data(session)
    if not data:
        await callback.answer("Ma'lumot topilmadi.", show_alert=True)
        return
    total = len(data)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    text = build_page(data, page)
    kb   = pagination_keyboard(rating_type, page, total)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.message(F.text == "🏆 Reyting")
async def rating_menu(message: Message):
    await message.answer(
        "🏆 <b>REYTING</b>\n\nQaysi ko'rsatkich bo'yicha reytingni ko'rmoqchisiz?",
        reply_markup=rating_menu_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "rating:menu")
async def rating_menu_cb(callback: CallbackQuery):
    try:
        await callback.message.edit_text(
            "🏆 <b>REYTING</b>\n\nQaysi ko'rsatkich bo'yicha reytingni ko'rmoqchisiz?",
            reply_markup=rating_menu_keyboard(),
            parse_mode="HTML"
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data == "rating:power")
async def rating_power(callback: CallbackQuery):
    await _show_rating(callback, "power", 0)

@router.callback_query(F.data == "rating:soldiers")
async def rating_soldiers(callback: CallbackQuery):
    await _show_rating(callback, "soldiers", 0)

@router.callback_query(F.data == "rating:gold")
async def rating_gold(callback: CallbackQuery):
    await _show_rating(callback, "gold", 0)

@router.callback_query(F.data == "rating:dragons")
async def rating_dragons(callback: CallbackQuery):
    await _show_rating(callback, "dragons", 0)

@router.callback_query(F.data == "rating:wins")
async def rating_wins(callback: CallbackQuery):
    await _show_rating(callback, "wins", 0)

@router.callback_query(F.data == "rating:alliances")
async def rating_alliances(callback: CallbackQuery):
    await _show_rating(callback, "alliances", 0)


@router.callback_query(F.data.startswith("rating_page:"))
async def rating_page(callback: CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    _, rating_type, page_str = parts
    if rating_type == "noop":
        await callback.answer()
        return
    try:
        page = int(page_str)
    except ValueError:
        await callback.answer()
        return
    await _show_rating(callback, rating_type, page)
