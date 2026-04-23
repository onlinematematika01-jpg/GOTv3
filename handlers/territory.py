"""
Hudud Garnizoni Mexanikasi (BOSQICH 6)
========================================
Hukmdor o'z hududiga askar, ajdar va skorpion joylashtira oladi.
Bu garnizon tashqi hujumda birinchi jangga kiradi.

Handlerlar:
  territory:manage            — Hudud boshqaruvi paneli (garnizon holati)
  territory:update_garrison   — Garnizonni yangilash (FSM: soldiers → dragons → scorpions)
"""

import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database.engine import AsyncSessionFactory
from database.repositories import UserRepo, HouseRepo, TerritoryGarrisonRepo
from database.models import RoleEnum

router = Router()
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# FSM States
# ─────────────────────────────────────────────

class TerritoryState(StatesGroup):
    waiting_garrison_soldiers  = State()
    waiting_garrison_dragons   = State()
    waiting_garrison_scorpions = State()


# ─────────────────────────────────────────────
# Helper: garnizon holat tugmasi
# ─────────────────────────────────────────────

def _garrison_manage_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏯 Garnizonni yangilash", callback_data="territory:update_garrison")],
        [InlineKeyboardButton(text="🔙 Orqaga",               callback_data="claim:panel")],
    ])


# ─────────────────────────────────────────────
# 6.1 — Hudud Boshqaruvi Paneli
# ─────────────────────────────────────────────

@router.callback_query(F.data == "territory:manage")
async def territory_manage_panel(callback: CallbackQuery):
    """
    Hukmdorlik paneli ichidagi Hudud boshqaruvi.
    Faqat HIGH_LORD roli uchun ochiq.
    """
    try:
        async with AsyncSessionFactory() as session:
            user_repo     = UserRepo(session)
            house_repo    = HouseRepo(session)
            garrison_repo = TerritoryGarrisonRepo(session)

            user = await user_repo.get_by_id(callback.from_user.id)
            if not user or user.role != RoleEnum.HIGH_LORD:
                await callback.answer("❌ Faqat Hukmdorlar uchun.", show_alert=True)
                return

            if not user.region:
                await callback.answer("❌ Hududingiz aniqlanmagan.", show_alert=True)
                return

            my_house = await house_repo.get_by_id(user.house_id)
            if not my_house:
                await callback.answer("❌ Xonadoningiz topilmadi.", show_alert=True)
                return

            garrison = await garrison_repo.get_by_region(user.region)

        g_soldiers  = garrison.soldiers  if garrison else 0
        g_dragons   = garrison.dragons   if garrison else 0
        g_scorpions = garrison.scorpions if garrison else 0

        text = (
            f"🏯 <b>Hudud Garnizoni — {user.region.value}</b>\n\n"
            f"Hozirgi garnizon:\n"
            f"⚔️ Askarlar: <b>{g_soldiers}</b>\n"
            f"🐉 Ajdarlar: <b>{g_dragons}</b>\n"
            f"🏹 Chayonlar: <b>{g_scorpions}</b>\n\n"
            f"🏰 Sizning xonadoningiz qo'shini:\n"
            f"⚔️ {my_house.total_soldiers} askar | "
            f"🐉 {my_house.total_dragons} ajdar | "
            f"🏹 {my_house.total_scorpions} chayon\n\n"
            f"<i>Garnizonni yangilash uchun askar miqdorini kiriting.\n"
            f"Eslatma: yangi garnizon o'rnatilganda xonadon qo'shinidan ayiriladi.</i>"
        )

        await callback.message.edit_text(text, reply_markup=_garrison_manage_kb(), parse_mode="HTML")

    except Exception as e:
        logger.exception("territory_manage_panel xatosi: %s", e)
        await callback.answer("❌ Texnik xato yuz berdi.", show_alert=True)


# ─────────────────────────────────────────────
# 6.2 — Garnizonni Yangilash (FSM boshlanishi)
# ─────────────────────────────────────────────

@router.callback_query(F.data == "territory:update_garrison")
async def territory_update_garrison_start(callback: CallbackQuery, state: FSMContext):
    """Garnizon yangilash jarayonini boshlaydi — askar sonini so'raydi."""
    try:
        async with AsyncSessionFactory() as session:
            user_repo = UserRepo(session)
            user = await user_repo.get_by_id(callback.from_user.id)
            if not user or user.role != RoleEnum.HIGH_LORD:
                await callback.answer("❌ Faqat Hukmdorlar uchun.", show_alert=True)
                return

        await state.set_state(TerritoryState.waiting_garrison_soldiers)
        await callback.message.answer(
            "⚔️ Garnizon uchun nechta <b>askar</b> joylashtirmoqchisiz?\n"
            "<i>(0 kiritsangiz — askar bo'lmaydi)</i>",
            parse_mode="HTML"
        )
        await callback.answer()

    except Exception as e:
        logger.exception("territory_update_garrison_start xatosi: %s", e)
        await callback.answer("❌ Texnik xato yuz berdi.", show_alert=True)


# ─────────────────────────────────────────────
# FSM — Askar soni
# ─────────────────────────────────────────────

@router.message(TerritoryState.waiting_garrison_soldiers)
async def territory_garrison_soldiers(message: Message, state: FSMContext):
    """Askar sonini qabul qilib, ajdar sonini so'raydi."""
    try:
        val = int(message.text.strip())
        if val < 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("❌ 0 yoki undan katta butun son kiriting.")
        return

    # Xonadon qo'shinini tekshirish
    async with AsyncSessionFactory() as session:
        user_repo  = UserRepo(session)
        house_repo = HouseRepo(session)
        user       = await user_repo.get_by_id(message.from_user.id)
        my_house   = await house_repo.get_by_id(user.house_id)

    if val > my_house.total_soldiers:
        await message.answer(
            f"❌ Yetarli askar yo'q.\n"
            f"Sizda: <b>{my_house.total_soldiers}</b> askar.\n"
            f"Qaytadan kiriting:",
            parse_mode="HTML"
        )
        return

    await state.update_data(g_soldiers=val)
    await state.set_state(TerritoryState.waiting_garrison_dragons)
    await message.answer(
        f"✅ Askar: <b>{val}</b>\n\n"
        f"🐉 Garnizon uchun nechta <b>ajdar</b> joylashtirmoqchisiz?\n"
        f"<i>Sizda: {my_house.total_dragons} ajdar (0 kiritsangiz — bo'lmaydi)</i>",
        parse_mode="HTML"
    )


# ─────────────────────────────────────────────
# FSM — Ajdar soni
# ─────────────────────────────────────────────

@router.message(TerritoryState.waiting_garrison_dragons)
async def territory_garrison_dragons(message: Message, state: FSMContext):
    """Ajdar sonini qabul qilib, chayon sonini so'raydi."""
    try:
        val = int(message.text.strip())
        if val < 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("❌ 0 yoki undan katta butun son kiriting.")
        return

    async with AsyncSessionFactory() as session:
        user_repo  = UserRepo(session)
        house_repo = HouseRepo(session)
        user       = await user_repo.get_by_id(message.from_user.id)
        my_house   = await house_repo.get_by_id(user.house_id)

    if val > my_house.total_dragons:
        await message.answer(
            f"❌ Yetarli ajdar yo'q.\n"
            f"Sizda: <b>{my_house.total_dragons}</b> ajdar.\n"
            f"Qaytadan kiriting:",
            parse_mode="HTML"
        )
        return

    await state.update_data(g_dragons=val)
    await state.set_state(TerritoryState.waiting_garrison_scorpions)
    await message.answer(
        f"✅ Ajdar: <b>{val}</b>\n\n"
        f"🏹 Garnizon uchun nechta <b>chayon</b> joylashtirmoqchisiz?\n"
        f"<i>Sizda: {my_house.total_scorpions} chayon (0 kiritsangiz — bo'lmaydi)</i>",
        parse_mode="HTML"
    )


# ─────────────────────────────────────────────
# FSM — Chayon soni + Tasdiqlash va DB yozish
# ─────────────────────────────────────────────

@router.message(TerritoryState.waiting_garrison_scorpions)
async def territory_garrison_confirm(message: Message, state: FSMContext):
    """
    Chayon sonini qabul qiladi va garnizoni yangilaydi:
      1. Xonadon qo'shinidan ayiradi
      2. TerritoryGarrison ga yozadi
    """
    try:
        val = int(message.text.strip())
        if val < 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("❌ 0 yoki undan katta butun son kiriting.")
        return

    data      = await state.get_data()
    soldiers  = data["g_soldiers"]
    dragons   = data["g_dragons"]
    scorpions = val

    try:
        async with AsyncSessionFactory() as session:
            user_repo     = UserRepo(session)
            house_repo    = HouseRepo(session)
            garrison_repo = TerritoryGarrisonRepo(session)

            user     = await user_repo.get_by_id(message.from_user.id)
            my_house = await house_repo.get_by_id(user.house_id)

            # Chayon miqdorini tekshirish
            if scorpions > my_house.total_scorpions:
                await message.answer(
                    f"❌ Yetarli chayon yo'q.\n"
                    f"Sizda: <b>{my_house.total_scorpions}</b> chayon.\n"
                    f"Qaytadan kiriting:",
                    parse_mode="HTML"
                )
                return

            # Yana bir bor tekshirish (state saqlangandan keyin xonadon o'zgarishi mumkin)
            if soldiers > my_house.total_soldiers:
                await message.answer(
                    f"❌ Yetarli askar qolmagan.\n"
                    f"Sizda: <b>{my_house.total_soldiers}</b> askar. Jarayon bekor qilindi."
                )
                await state.clear()
                return

            if dragons > my_house.total_dragons:
                await message.answer(
                    f"❌ Yetarli ajdar qolmagan.\n"
                    f"Sizda: <b>{my_house.total_dragons}</b> ajdar. Jarayon bekor qilindi."
                )
                await state.clear()
                return

            # Xonadon qo'shinini kamaytirish (manfiy delta)
            await house_repo.update_military(
                user.house_id,
                soldiers  = -soldiers,
                dragons   = -dragons,
                scorpions = -scorpions,
            )

            # Garnizonni yangilash (to'liq almashtirish)
            await garrison_repo.set_garrison(
                region           = user.region,
                hukmdor_house_id = user.house_id,
                soldiers         = soldiers,
                dragons          = dragons,
                scorpions        = scorpions,
            )

            await session.commit()

        await state.clear()
        await message.answer(
            f"✅ <b>Hudud garnizoni yangilandi!</b>\n\n"
            f"🏯 <b>{user.region.value}</b> hududiga joylashtirildi:\n"
            f"⚔️ {soldiers} askar | 🐉 {dragons} ajdar | 🏹 {scorpions} chayon\n\n"
            f"Bu qo'shinlar tashqi hujum bo'lsa birinchi jangga kiradi.",
            parse_mode="HTML"
        )

    except Exception as e:
        logger.exception("territory_garrison_confirm xatosi: %s", e)
        await state.clear()
        await message.answer("❌ Texnik xato yuz berdi. Qaytadan urinib ko'ring.")
