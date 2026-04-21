from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database.engine import AsyncSessionFactory
from database.repositories import RatingRepo, CustomItemRepo, AllianceGroupRepo, HouseRepo, PrisonerRepo
from database.models import RegionEnum
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


async def _get_deposit_data(session) -> list:
    """Faol omonatlarni umumiy summasi bo'yicha tartiblaydi"""
    from database.repositories import IronBankDepositRepo, MarketRepo
    dep_repo = IronBankDepositRepo(session)
    market_repo = MarketRepo(session)
    prices = await market_repo.get_all_prices()
    from config.settings import settings as cfg
    s_price  = prices.get("soldier",  cfg.SOLDIER_PRICE)
    d_price  = prices.get("dragon",   cfg.DRAGON_PRICE)
    sc_price = prices.get("scorpion", cfg.SCORPION_PRICE)

    deposits = await dep_repo.get_all_active()
    # House nomini olish uchun
    from database.repositories import HouseRepo
    house_repo = HouseRepo(session)
    result = []
    for dep in deposits:
        house = await house_repo.get_by_id(dep.house_id)
        if not house:
            continue
        mil_val = dep.soldiers * s_price + dep.dragons * d_price + dep.scorpions * sc_price
        total = dep.gold + mil_val
        result.append({
            "house_name": house.name,
            "gold": dep.gold,
            "soldiers": dep.soldiers,
            "dragons": dep.dragons,
            "scorpions": dep.scorpions,
            "mil_val": mil_val,
            "total": total,
            "s_price": s_price,
            "d_price": d_price,
            "sc_price": sc_price,
        })
    result.sort(key=lambda x: x["total"], reverse=True)
    return result


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


def _build_deposit_page(data: list, page: int) -> str:
    start = page * PAGE_SIZE
    lines = ["🏦 <b>OMONAT REYTINGI</b>\n"]
    if not data:
        lines.append("Hozircha hech kim omonat ochmagan.")
        return "\n".join(lines)
    for i, d in enumerate(data[start: start + PAGE_SIZE]):
        mil_parts = []
        if d["soldiers"]: mil_parts.append(f"🗡️{d['soldiers']:,}×{d['s_price']}")
        if d["dragons"]:  mil_parts.append(f"🐉{d['dragons']}×{d['d_price']}")
        if d["scorpions"]:mil_parts.append(f"🏹{d['scorpions']}×{d['sc_price']}")
        mil_line = "  |  " + "  ".join(mil_parts) if mil_parts else ""
        lines.append(
            f"{get_medal(start + i)} <b>{d['house_name']}</b>\n"
            f"   📊 {d['total']:,} tanga  |  💰 {d['gold']:,}"
            + mil_line
        )
    return "\n".join(lines)


REGION_EMOJIS = {
    "Shimol": "❄️",
    "Vodiy": "🏔️",
    "Daryo yerlari": "🌊",
    "Temir orollar": "⚓",
    "G'arbiy yerlar": "💎",
    "Qirollik bandargohi": "👑",
    "Tyrellar vodiysi": "🌹",
    "Bo'ronli yerlar": "⛈️",
    "Dorn": "☀️",
}


async def _get_prisoners_data(session) -> list:
    """Har bir xonadon ushlab turgan aktiv asirlar soni bo'yicha reyting"""
    return await PrisonerRepo(session).get_captors_ranking()


def _build_prisoners_page(data: list, page: int) -> str:
    start = page * PAGE_SIZE
    lines = ["⛓️ <b>ASIRLAR REYTINGI</b>\n"]
    if not data:
        lines.append("Hozircha hech kim asirda emas.")
        return "\n".join(lines)
    for i, entry in enumerate(data[start: start + PAGE_SIZE]):
        house = entry["house"]
        prisoners = entry["prisoners"]
        prisoner_list_str = "\n".join(
            f"   • {p.prisoner_user.full_name}"
            for p in prisoners
        )
        lines.append(
            f"{get_medal(start + i)} <b>{house.name}</b>  —  {entry['count']} asir\n"
            f"{prisoner_list_str}"
        )
    return "\n\n".join(lines)


async def _get_regions_data(session) -> list:
    house_repo = HouseRepo(session)
    alliance_repo = AllianceGroupRepo(session)
    item_repo = CustomItemRepo(session)

    all_houses = await house_repo.get_all()
    # Load all active alliance groups for power calc
    all_alliances = await alliance_repo.get_alliance_power_ranking(limit=1000)

    result = []
    for region in RegionEnum:
        houses = [h for h in all_houses if h.region == region]
        if not houses:
            continue

        # Hukmdorni topish (high_lord_id bor xonadon)
        ruler_house = next((h for h in houses if h.high_lord_id is not None), None)

        # Umumiy harbiy kuch (xonadonlar + custom items)
        total_power = 0
        for h in houses:
            items = await item_repo.get_house_items_with_info(h.id)
            extra = sum(r.item.attack_power * r.quantity + r.item.defense_power * r.quantity for r in items)
            base = h.total_soldiers + h.total_dragons * 200 + h.total_scorpions * 25
            total_power += base + extra

        total_soldiers = sum(h.total_soldiers for h in houses)
        total_dragons = sum(h.total_dragons for h in houses)
        total_scorpions = sum(h.total_scorpions for h in houses)

        # Ushbu hududdagi kuchli ittifoqlar
        region_alliances = []
        for entry in all_alliances:
            member_house_ids = {m.house_id for m in entry["group"].members if m.house}
            region_house_ids = {h.id for h in houses}
            overlap = member_house_ids & region_house_ids
            if overlap:
                region_alliances.append(entry)

        result.append({
            "region": region,
            "houses": houses,
            "house_count": len(houses),
            "ruler_house": ruler_house,
            "total_power": total_power,
            "total_soldiers": total_soldiers,
            "total_dragons": total_dragons,
            "total_scorpions": total_scorpions,
            "alliances": region_alliances[:3],  # top 3
        })

    result.sort(key=lambda x: x["total_power"], reverse=True)
    return result


def _build_regions_page(data: list, page: int) -> str:
    start = page * PAGE_SIZE
    lines = ["🗺️ <b>HUDUDLAR HOLATI</b>\n"]
    for i, entry in enumerate(data[start: start + PAGE_SIZE]):
        region = entry["region"]
        emoji = REGION_EMOJIS.get(region.value, "🏴")
        ruler_text = f"👑 <b>{entry['ruler_house'].name}</b>" if entry["ruler_house"] else "⚠️ <i>Hukmdorsiz</i>"

        alliance_text = ""
        if entry["alliances"]:
            names = ", ".join(a["group"].name for a in entry["alliances"])
            alliance_text = f"\n   ⚔️ Ittifoqlar: <i>{names}</i>"

        lines.append(
            f"{emoji} <b>{region.value}</b>\n"
            f"   🏠 Xonadonlar: {entry['house_count']} ta  |  {ruler_text}\n"
            f"   ⚡ {entry['total_power']:,}  |  🗡️ {entry['total_soldiers']:,}  🐉 {entry['total_dragons']}  🏹 {entry['total_scorpions']}"
            + alliance_text
        )
    return "\n\n".join(lines)


RATING_HANDLERS = {
    "power":     (_get_power_data,     _build_power_page),
    "soldiers":  (_get_soldiers_data,  _build_soldiers_page),
    "gold":      (_get_gold_data,      _build_gold_page),
    "dragons":   (_get_dragons_data,   _build_dragons_page),
    "wins":      (_get_wins_data,      _build_wins_page),
    "alliances": (_get_alliances_data, _build_alliances_page),
    "deposit":   (_get_deposit_data,   _build_deposit_page),
    "regions":   (_get_regions_data,   _build_regions_page),
    "prisoners": (_get_prisoners_data, _build_prisoners_page),
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

@router.callback_query(F.data == "rating:deposit")
async def rating_deposit(callback: CallbackQuery):
    await _show_rating(callback, "deposit", 0)

@router.callback_query(F.data == "rating:regions")
async def rating_regions(callback: CallbackQuery):
    await _show_rating(callback, "regions", 0)

@router.callback_query(F.data == "rating:prisoners")
async def rating_prisoners(callback: CallbackQuery):
    await _show_rating(callback, "prisoners", 0)


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
