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
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime, timedelta
from sqlalchemy import select

from database.engine import AsyncSessionFactory
from database.repositories import (
    UserRepo, HouseRepo, WarRepo,
    HukmdorClaimRepo, ChronicleRepo,
    TerritoryGarrisonRepo,
)
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


# ─────────────────────────────────────────────
# BOSQICH 8 — FSM States
# ─────────────────────────────────────────────

class VassalState(StatesGroup):
    waiting_troop_amount = State()  # Vassal nechta askar yuborishini so'raydi


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

        my_house = await house_repo.get_by_id(user.house_id)
        if not my_house:
            await message.answer("❌ Xonadoningiz topilmadi.")
            return

        # Vassal bo'lsa — isyon qoidasi tekshiriladi
        if my_house.is_under_occupation and my_house.vassal_since:
            days_as_vassal = (datetime.utcnow() - my_house.vassal_since).days
            if days_as_vassal < 2:
                remaining = 2 - days_as_vassal
                await message.answer(
                    f"⛓️ <b>Isyon uchun vaqt kelgani yo'q!</b>\n\n"
                    f"Siz vassal bo'lganingizga <b>{days_as_vassal}</b> kun bo'ldi.\n"
                    f"Isyon qilish uchun kamida <b>2 kun</b> o'tishi kerak.\n"
                    f"⏳ Yana <b>{remaining}</b> kun kutishingiz lozim.",
                    parse_mode="HTML"
                )
                return

            # BOSQICH 9 — Garnizon nazorati: isyon bloki
            if my_house.occupier_house_id:
                garrison_repo = TerritoryGarrisonRepo(session)
                garrison = await garrison_repo.get_by_region(user.region)
                if garrison and garrison.soldiers > 0:
                    hukmdor_house = await house_repo.get_by_id(my_house.occupier_house_id)
                    all_vassals = await house_repo.get_vassals_by_hukmdor(hukmdor_house.id)
                    total_vassal_soldiers = sum(h.total_soldiers for h in all_vassals)
                    half_vassal = total_vassal_soldiers // 2
                    if garrison.soldiers >= half_vassal:
                        await message.answer(
                            f"⛓️ <b>Isyon imkonsiz!</b>\n\n"
                            f"Hukmdor hududga <b>{garrison.soldiers}</b> askar joylashtirgan.\n"
                            f"Bu barcha vassal qo'shinining yarmidan "
                            f"(<b>{half_vassal}</b>) ko'p.\n\n"
                            f"Avval garnizonni sindirmasdan isyon qila olmaysiz.",
                            parse_mode="HTML"
                        )
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

        # Vassal holatini o'rnatish — o'lpon tizimi uchun
        await house_repo.set_occupation(user.house_id, claimant.id, tax_rate=0.0)

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

        # Mavjud urush bormi?
        active = await war_repo.get_active_war(user.house_id)
        if active:
            await session.commit()
            await callback.answer("⚠️ Allaqachon faol urushingiz bor!", show_alert=True)
            return

        # Civil urush darhol boshlanadi — vaqtga bog'liq emas
        now = datetime.utcnow()
        grace_ends = now + timedelta(minutes=settings.GRACE_PERIOD_MINUTES)
        war = await war_repo.create_war(claimant.id, defender.id, grace_ends)
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
        # Da'vogar BARCHA urushlarni yutgan bo'lsa u HIGH_LORD
        # Agar da'vogar hech bo'lmasa bitta urushda yutqazsa —
        # uni mag'lub qilgan xonadon g'olib
        ended_wars = [w for w in wars if w.status == WarStatusEnum.ENDED]
        if not ended_wars:
            continue

        claimant_won_all = all(
            w.winner_house_id == claim.claimant_house_id
            for w in ended_wars
        )

        if claimant_won_all:
            winner_id = claim.claimant_house_id
        else:
            # G'alaba sonini sanash — eng ko'p yutgan xonadon HIGH_LORD
            wins: dict[int, int] = {}
            for w in ended_wars:
                if w.winner_house_id:
                    wins[w.winner_house_id] = wins.get(w.winner_house_id, 0) + 1
            winner_id = max(wins, key=lambda k: wins[k]) if wins else None

        await claim_repo.set_status(claim.id, ClaimStatusEnum.COMPLETED)

        if winner_id:
            await claim_repo.resolve_hukmdor(claim.region, winner_id, bot)

            # Mag'lub bo'lgan barcha xonadonlarni vassal qilish
            for w in ended_wars:
                loser_id = (
                    w.defender_house_id
                    if w.winner_house_id == w.attacker_house_id
                    else w.attacker_house_id
                )
                if loser_id != winner_id:
                    await house_repo.set_occupation(loser_id, winner_id, tax_rate=0.0)

            winner = await house_repo.get_by_id(winner_id)
            from utils.chronicle import post_to_chronicle
            text = (
                f"👑 <b>YANGI HUKMDOR — URUSH ORQALI!</b>\n\n"
                f"<b>{winner.name}</b> barcha raqiblarini mag'lub etib "
                f"<b>{claim.region.value}</b> hududining Hukmdori bo'ldi!\n"
                f"⚔️ Qilich bilan hokimiyat qo'lga kiritildi."
            )
            await post_to_chronicle(bot, text)


# ═══════════════════════════════════════════════════════════════
# BOSQICH 8 — Hukmdorlik Paneli va Vassal Askar So'rash
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "claim:panel")
async def hukmdor_claim_panel(callback: CallbackQuery):
    """Hukmdorlik paneli — faqat HIGH_LORD uchun"""
    try:
        async with AsyncSessionFactory() as session:
            user_repo     = UserRepo(session)
            house_repo    = HouseRepo(session)
            garrison_repo = TerritoryGarrisonRepo(session)

            user = await user_repo.get_by_id(callback.from_user.id)
            if not user or user.role != RoleEnum.HIGH_LORD:
                await callback.answer("❌ Faqat Hukmdor uchun.", show_alert=True)
                return

            vassal_houses       = await house_repo.get_vassals_by_hukmdor(user.house_id)
            total_vassal_soldiers = sum(h.total_soldiers for h in vassal_houses)

            garrison            = await garrison_repo.get_by_region(user.region)
            garrison_soldiers   = garrison.soldiers if garrison else 0

        half_vassal     = total_vassal_soldiers // 2
        rebellion_safe  = garrison_soldiers >= half_vassal

        text = (
            f"👑 <b>Hukmdorlik Paneli — {user.region.value}</b>\n\n"
            f"🏰 Vassal xonadonlar: <b>{len(vassal_houses)}</b>\n"
            f"⚔️ Jami vassal qo'shini: <b>{total_vassal_soldiers}</b>\n"
            f"🏯 Hududdagi garnizon: <b>{garrison_soldiers}</b>\n\n"
            f"{'✅ Isyon xavfi yo\'q' if rebellion_safe else '⚠️ Isyon xavfi bor! Garnizonni kuchaytiring.'}\n"
            f"<i>(Garnizon ≥ vassal qo'shini yarmi bo'lsa — isyon bo'lmaydi)</i>"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏯 Hudud Boshqaruvi",    callback_data="territory:manage")],
            [InlineKeyboardButton(text="⚔️ Vassal Askar So'rash", callback_data="claim:request_troops")],
            [InlineKeyboardButton(text="🔙 Bosh menyu",           callback_data="main:menu")],
        ])
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

    except Exception as e:
        logger.exception("hukmdor_claim_panel xatosi: %s", e)
        await callback.answer("❌ Texnik xato yuz berdi.", show_alert=True)


@router.callback_query(F.data == "claim:request_troops")
async def request_vassal_troops(callback: CallbackQuery):
    """Hukmdor vassal xonadonlardan askar so'raydi"""
    try:
        async with AsyncSessionFactory() as session:
            user_repo  = UserRepo(session)
            house_repo = HouseRepo(session)

            user     = await user_repo.get_by_id(callback.from_user.id)
            if not user or user.role != RoleEnum.HIGH_LORD:
                await callback.answer("❌ Faqat Hukmdor uchun.", show_alert=True)
                return

            my_house      = await house_repo.get_by_id(user.house_id)
            vassal_houses = await house_repo.get_vassals_by_hukmdor(user.house_id)

        if not vassal_houses:
            await callback.answer("❌ Vassal xonadonlaringiz yo'q.", show_alert=True)
            return

        sent_count = 0
        for vassal in vassal_houses:
            if not vassal.lord_id:
                continue
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="✅ Askar beraman",
                    callback_data=f"vassal:troops:accept:{my_house.id}"
                ),
                InlineKeyboardButton(
                    text="❌ Rad etaman",
                    callback_data=f"vassal:troops:reject:{my_house.id}"
                ),
            ]])
            try:
                await callback.bot.send_message(
                    vassal.lord_id,
                    f"👑 <b>{my_house.name}</b> (Hukmdor) sizdan askar so'ramoqda!\n\n"
                    f"Nechta askar yuborasiz?",
                    reply_markup=kb,
                    parse_mode="HTML"
                )
                sent_count += 1
            except Exception:
                pass

        await callback.answer(
            f"✅ So'rov {sent_count} ta vassalga yuborildi." if sent_count
            else "⚠️ Hech bir vassalga yubora olmadi.",
            show_alert=True
        )

    except Exception as e:
        logger.exception("request_vassal_troops xatosi: %s", e)
        await callback.answer("❌ Texnik xato yuz berdi.", show_alert=True)


@router.callback_query(F.data.startswith("vassal:troops:"))
async def vassal_troops_response(callback: CallbackQuery, state: FSMContext):
    """Vassal askar so'roviga javob beradi"""
    try:
        parts            = callback.data.split(":")   # vassal troops accept/reject hukmdor_house_id
        decision         = parts[2]
        hukmdor_house_id = int(parts[3])

        if decision == "reject":
            await callback.message.edit_text("❌ Askar so'rovini rad etdingiz.")
            # Hukmdorga xabar
            async with AsyncSessionFactory() as session:
                house_repo = HouseRepo(session)
                user_repo  = UserRepo(session)
                hukmdor_house = await house_repo.get_by_id(hukmdor_house_id)
                user = await user_repo.get_by_id(callback.from_user.id)
                my_house = await house_repo.get_by_id(user.house_id) if user and user.house_id else None

            if hukmdor_house and hukmdor_house.lord_id:
                try:
                    await callback.bot.send_message(
                        hukmdor_house.lord_id,
                        f"❌ <b>{my_house.name if my_house else 'Vassal'}</b> askar so'rovingizni rad etdi.",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
            return

        # Qabul — nechta askar yuborish so'raladi
        await state.update_data(troop_request_house=hukmdor_house_id)
        await state.set_state(VassalState.waiting_troop_amount)
        await callback.message.edit_text(
            "✅ Nechta askar yubormoqchisiz?\n"
            "<i>(Raqam kiriting, 0 — askar yubormaslik)</i>",
            parse_mode="HTML"
        )

    except Exception as e:
        logger.exception("vassal_troops_response xatosi: %s", e)
        await callback.answer("❌ Texnik xato yuz berdi.", show_alert=True)


@router.message(VassalState.waiting_troop_amount)
async def vassal_troops_send(message: Message, state: FSMContext):
    """Vassal askar miqdorini kiritadi va xonadonlar o'rtasida ko'chiradi"""
    try:
        amount = int(message.text.strip())
        if amount < 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("❌ 0 yoki undan katta son kiriting.")
        return

    data             = await state.get_data()
    hukmdor_house_id = data.get("troop_request_house")

    if amount == 0:
        await state.clear()
        await message.answer("ℹ️ Askar yubormadingiz.")
        return

    try:
        async with AsyncSessionFactory() as session:
            user_repo  = UserRepo(session)
            house_repo = HouseRepo(session)

            user     = await user_repo.get_by_id(message.from_user.id)
            if not user or not user.house_id:
                await message.answer("❌ Xonadoningiz topilmadi.")
                await state.clear()
                return

            my_house      = await house_repo.get_by_id(user.house_id)
            hukmdor_house = await house_repo.get_by_id(hukmdor_house_id)

            if amount > my_house.total_soldiers:
                await message.answer(
                    f"❌ Yetarli askar yo'q.\n"
                    f"Sizda: <b>{my_house.total_soldiers}</b> askar.",
                    parse_mode="HTML"
                )
                return

            # Vassaldan ayirish, hukmdorga qo'shish
            await house_repo.update_military(my_house.id,    soldiers=-amount)
            await house_repo.update_military(hukmdor_house_id, soldiers=+amount)
            await session.commit()

        await state.clear()
        await message.answer(
            f"✅ <b>{amount}</b> askar <b>{hukmdor_house.name}</b> ga yuborildi.",
            parse_mode="HTML"
        )

        # Hukmdorga xabar
        if hukmdor_house and hukmdor_house.lord_id:
            try:
                await message.bot.send_message(
                    hukmdor_house.lord_id,
                    f"⚔️ <b>{my_house.name}</b> vassalingiz <b>{amount}</b> askar yubordi!",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    except Exception as e:
        logger.exception("vassal_troops_send xatosi: %s", e)
        await state.clear()
        await message.answer("❌ Texnik xato yuz berdi. Qaytadan urinib ko'ring.")
