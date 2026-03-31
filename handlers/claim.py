"""
Hukmdorlik Da'vosi Mexanikasi
==============================
1. Lord "👑 Hukmdorlik Da'vosi" ni bosadi
2. Bot bir hududdagi boshqa barcha xonadonlarga xabar yuboradi
3. Har bir xonadon: ✅ Qabul (vassal bo'lish) yoki ❌ Rad (urush)
4. Qabul qilganlar vassal bo'ladi
5. Rad etganlar bilan CIVIL urush boshlanadi (urush mexanikasi ishga tushadi)
6. Barcha urushlar tugagach — da'vogar HIGH_LORD bo'ladi
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from datetime import datetime, timedelta
from sqlalchemy import select

from database.engine import AsyncSessionFactory
from database.repositories import UserRepo, HouseRepo, WarRepo, HukmdorClaimRepo, ChronicleRepo
from database.models import (
    RoleEnum, WarTypeEnum, ClaimStatusEnum,
    HukmdorClaim, HukmdorClaimResponse, War, WarStatusEnum
)
from keyboards import main_menu_keyboard
from utils.chronicle import post_to_chronicle, format_chronicle
from config.settings import settings
import logging

router = Router()
logger = logging.getLogger(__name__)


def _claim_response_keyboard(claim_id: int):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Qabul (Vassal bo'laman)", callback_data=f"claim:accept:{claim_id}"),
        InlineKeyboardButton(text="⚔️ Rad (Urush!)", callback_data=f"claim:reject:{claim_id}"),
    ]])


@router.message(F.text == "👑 Hukmdorlik Da'vosi")
async def start_claim(message: Message):
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)
        claim_repo = HukmdorClaimRepo(session)

        user = await user_repo.get_by_id(message.from_user.id)

        if not user or user.role not in [RoleEnum.LORD, RoleEnum.HIGH_LORD]:
            await message.answer("❌ Faqat Lordlar hukmdorlik da'vosini ochishi mumkin.")
            return

        if not user.house_id or not user.region:
            await message.answer("❌ Xonadon yoki hududingiz aniqlanmagan.")
            return

        # Hududda faqat 1 ta xonadon bo'lsa — da'vo ma'nosiz
        same_region_houses = await house_repo.get_all_by_region(user.region)
        other_houses = [h for h in same_region_houses if h.id != user.house_id]

        if not other_houses:
            await message.answer(
                "ℹ️ Hududingizda boshqa xonadon yo'q.\n"
                "Siz allaqachon yagona xonadon lordidasiz!"
            )
            return

        # Allaqachon faol da'vo bormi?
        existing = await claim_repo.get_active_claim(user.region)
        if existing:
            await message.answer("❌ Hududda allaqachon faol hukmdorlik da'vosi mavjud.")
            return

        # Da'vo yaratish
        claim = await claim_repo.create_claim(user.house_id, user.region)

        # Boshqa xonadonlar uchun javob yozuvlari
        for house in other_houses:
            await claim_repo.add_response(claim.id, house.id)

        await session.commit()

        # Boshqa xonadon lordlariga xabar
        my_house = await house_repo.get_by_id(user.house_id)
        notified = 0
        for house in other_houses:
            if house.lord_id:
                try:
                    await message.bot.send_message(
                        house.lord_id,
                        f"👑 <b>HUKMDORLIK DA'VOSI!</b>\n\n"
                        f"<b>{my_house.name}</b> xonadoni "
                        f"<b>{user.region.value}</b> hududining Hukmdori bo'lish "
                        f"da'vosini ochdi!\n\n"
                        f"Qaror qiling:\n"
                        f"✅ <b>Qabul</b> — Vassal bo'lasiz, o'lpon to'laysiz\n"
                        f"⚔️ <b>Rad</b> — Urush boshlanadi!\n\n"
                        f"⏰ Javob berish muddati: 1 soat",
                        reply_markup=_claim_response_keyboard(claim.id),
                        parse_mode="HTML"
                    )
                    notified += 1
                except Exception as e:
                    logger.warning(f"Da'vo xabari yuborishda xato: {e}")

        # Xronika
        chronicle_repo = ChronicleRepo(session)
        text = (
            f"👑 <b>HUKMDORLIK DA'VOSI!</b>\n\n"
            f"<b>{my_house.name}</b> xonadoni <b>{user.region.value}</b> "
            f"hududining Hukmdori bo'lish da'vosini ochdi!\n"
            f"Javob kutilayotgan xonadonlar: {len(other_houses)} ta"
        )
        tg_id = await post_to_chronicle(message.bot, text)
        await chronicle_repo.add("claim_opened", text, house_id=user.house_id, tg_msg_id=tg_id)

        await message.answer(
            f"👑 <b>Da'voz ochildi!</b>\n\n"
            f"Hudud: <b>{user.region.value}</b>\n"
            f"Xabarnoma yuborildi: {notified} ta xonadonga\n\n"
            f"⏰ 1 soat ichida javob bermagan xonadonlar "
            f"avtomatik rad etilgan hisoblanadi (urush boshlanadi).",
            parse_mode="HTML"
        )


@router.callback_query(F.data.startswith("claim:accept:"))
async def claim_accept(callback: CallbackQuery):
    claim_id = int(callback.data.split(":")[2])

    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)
        claim_repo = HukmdorClaimRepo(session)

        user = await user_repo.get_by_id(callback.from_user.id)
        if not user or not user.house_id:
            await callback.answer("❌ Xonadoningiz yo'q.", show_alert=True)
            return

        resp = await claim_repo.get_response(claim_id, user.house_id)
        if not resp:
            await callback.answer("❌ Bu da'vo sizga tegishli emas.", show_alert=True)
            return
        if resp.accepted is not None:
            await callback.answer("ℹ️ Siz allaqachon javob bergansiz.", show_alert=True)
            return

        # Javobni saqlash
        await claim_repo.set_response(claim_id, user.house_id, accepted=True)

        # Da'vogar xonadon va hukmdor nomi
        result = await session.execute(
            select(HukmdorClaim).where(HukmdorClaim.id == claim_id)
        )
        claim = result.scalar_one_or_none()
        claimant = await house_repo.get_by_id(claim.claimant_house_id)

        await callback.answer("✅ Qabul qildingiz — vassal bo'ldingiz!")
        await callback.message.edit_text(
            f"✅ <b>Qabul qildingiz!</b>\n\n"
            f"<b>{claimant.name}</b> xonadonini Hukmdor sifatida tan oldingiz.\n"
            f"Siz vassal bo'ldingiz va o'lpon to'laysiz.",
            parse_mode="HTML"
        )

        # Barcha javoblarni tekshirish
        await _check_claim_completion(claim_id, callback.bot, session)


@router.callback_query(F.data.startswith("claim:reject:"))
async def claim_reject(callback: CallbackQuery):
    claim_id = int(callback.data.split(":")[2])

    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)
        claim_repo = HukmdorClaimRepo(session)
        war_repo = WarRepo(session)

        user = await user_repo.get_by_id(callback.from_user.id)
        if not user or not user.house_id:
            await callback.answer("❌ Xonadoningiz yo'q.", show_alert=True)
            return

        resp = await claim_repo.get_response(claim_id, user.house_id)
        if not resp:
            await callback.answer("❌ Bu da'vo sizga tegishli emas.", show_alert=True)
            return
        if resp.accepted is not None:
            await callback.answer("ℹ️ Siz allaqachon javob bergansiz.", show_alert=True)
            return

        # Javobni saqlash
        await claim_repo.set_response(claim_id, user.house_id, accepted=False)

        result = await session.execute(
            select(HukmdorClaim).where(HukmdorClaim.id == claim_id)
        )
        claim = result.scalar_one_or_none()
        claimant = await house_repo.get_by_id(claim.claimant_house_id)
        defender = await house_repo.get_by_id(user.house_id)

        # Status -> IN_PROGRESS
        await claim_repo.set_status(claim_id, ClaimStatusEnum.IN_PROGRESS)

        # Urush vaqtini tekshirish
        now = datetime.utcnow()
        local_hour = (now.hour + 5) % 24
        if not (settings.WAR_START_HOUR <= local_hour < settings.WAR_DECLARE_DEADLINE):
            await callback.answer(
                "⚠️ Rad etdingiz! Urush faqat 19:00–22:00 da boshlanadi.",
                show_alert=True
            )
            await callback.message.edit_text(
                f"⚔️ <b>Rad etdingiz!</b>\n\n"
                f"Urush vaqti kelganda (19:00–22:00) avtomatik boshlanadi.",
                parse_mode="HTML"
            )
            return

        # Mavjud urush bormi?
        active = await war_repo.get_active_war(user.house_id)
        if active:
            await callback.answer("⚠️ Allaqachon faol urushingiz bor!", show_alert=True)
            return

        grace_ends = now + timedelta(minutes=settings.GRACE_PERIOD_MINUTES)
        war = await war_repo.create_war(
            claimant.id, defender.id, grace_ends
        )
        # war_type = civil va claim_id ni to'ldirish
        from sqlalchemy import update
        from database.models import War
        await session.execute(
            update(War).where(War.id == war.id).values(
                war_type=WarTypeEnum.CIVIL.value,
                claim_id=claim_id,
            )
        )
        await session.commit()

        await callback.answer("⚔️ Rad etdingiz — URUSH boshlanmoqda!")
        await callback.message.edit_text(
            f"⚔️ <b>Rad etdingiz!</b>\n\n"
            f"<b>{claimant.name}</b> bilan ichki urush boshlanmoqda!\n"
            f"⏰ Grace Period: {settings.GRACE_PERIOD_MINUTES} daqiqa\n"
            f"Bu Hukmdorlik uchun jang — g'olib Hukmdor bo'ladi!",
            parse_mode="HTML"
        )

        # Da'vogarga xabar
        if claimant.lord_id:
            try:
                await callback.bot.send_message(
                    claimant.lord_id,
                    f"⚔️ <b>{defender.name}</b> da'vozingizni rad etdi!\n"
                    f"Hudud: <b>{claim.region.value}</b>\n"
                    f"Grace Period: {settings.GRACE_PERIOD_MINUTES} daqiqa",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        await _check_claim_completion(claim_id, callback.bot, session)


async def _check_claim_completion(claim_id: int, bot, session):
    """Barcha javoblar kelganda da'voni yakunlash yoki Hukmdorni belgilash"""
    claim_repo = HukmdorClaimRepo(session)
    house_repo = HouseRepo(session)

    result = await session.execute(
        select(HukmdorClaim).where(HukmdorClaim.id == claim_id)
    )
    claim = result.scalar_one_or_none()
    if not claim:
        return

    responses = await claim_repo.get_all_responses(claim_id)

    # Javob bermaganlar bormi?
    pending = [r for r in responses if r.accepted is None]
    if pending:
        return  # Hali kutilmoqda

    # Barcha javob keldi — rad etganlar bormi?
    rejected = [r for r in responses if r.accepted is False]

    if not rejected:
        # Hammasi qabul qildi — da'vogar darhol HUKMDOR!
        await claim_repo.set_status(claim_id, ClaimStatusEnum.COMPLETED)
        await claim_repo.resolve_hukmdor(claim.region, claim.claimant_house_id, bot)

        claimant = await house_repo.get_by_id(claim.claimant_house_id)
        from utils.chronicle import post_to_chronicle
        text = (
            f"👑 <b>YANGI HUKMDOR!</b>\n\n"
            f"<b>{claimant.name}</b> barcha xonadonlar tomonidan "
            f"<b>{claim.region.value}</b> hududining Hukmdori sifatida tan olindi!\n"
            f"Tinch yo'l bilan hokimiyat o'tdi. 🕊️"
        )
        await post_to_chronicle(bot, text)
    # Agar rad etganlar bor bo'lsa — urushlar ketmoqda, scheduler hal qiladi


async def check_claim_wars_ended(bot, session):
    """
    Scheduler tomonidan chaqiriladi: Civil urushlar tugaganda da'voni yakunlash.
    Barcha civil urushlar tugagan bo'lsa — g'olibni aniqlash.
    """
    from sqlalchemy import select
    from database.models import HukmdorClaim, War, ClaimStatusEnum, WarStatusEnum, WarTypeEnum

    # Faol da'volar
    result = await session.execute(
        select(HukmdorClaim).where(
            HukmdorClaim.status == ClaimStatusEnum.IN_PROGRESS
        )
    )
    active_claims = result.scalars().all()

    claim_repo = HukmdorClaimRepo(session)
    house_repo = HouseRepo(session)

    for claim in active_claims:
        # Bu da'voga bog'liq barcha urushlar
        result = await session.execute(
            select(War).where(
                War.claim_id == claim.id,
                War.war_type == WarTypeEnum.CIVIL.value,
            )
        )
        wars = result.scalars().all()

        active_wars = [w for w in wars if w.status != WarStatusEnum.ENDED]
        if active_wars:
            continue  # Hali tugamagan urushlar bor

        # Barcha urushlar tugadi — g'olibni hisoblash
        # Da'vogar barcha urushlarni yutdimi?
        claimant_lost = any(
            w.winner_house_id != claim.claimant_house_id
            for w in wars if w.status == WarStatusEnum.ENDED
        )

        if claimant_lost:
            # Da'vogar yutqazdi — g'olib uni mag'lub qilgan xonadon
            # Oxirgi da'vogarni yutgan xonadonni topamiz
            winner_id = None
            for w in wars:
                if w.winner_house_id != claim.claimant_house_id:
                    winner_id = w.winner_house_id
                    break
        else:
            winner_id = claim.claimant_house_id

        await claim_repo.set_status(claim.id, ClaimStatusEnum.COMPLETED)

        if winner_id:
            await claim_repo.resolve_hukmdor(claim.region, winner_id, bot)
            winner = await house_repo.get_by_id(winner_id)
            from utils.chronicle import post_to_chronicle
            text = (
                f"👑 <b>YANGI HUKMDOR — URUSH ORQALI!</b>\n\n"
                f"<b>{winner.name}</b> barcha raqiblarini mag'lub etib "
                f"<b>{claim.region.value}</b> hududining Hukmdori bo'ldi!\n"
                f"⚔️ Qilich bilan hokimiyat qo'lga kiritildi."
            )
            await post_to_chronicle(bot, text)
