from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database.engine import AsyncSessionFactory
from database.repositories import (
    UserRepo, HouseRepo, WarRepo, PrisonerRepo, ChronicleRepo
)
from database.models import RoleEnum, PrisonerStatusEnum
from utils.chronicle import post_to_chronicle, format_chronicle
import logging

router = Router()
logger = logging.getLogger(__name__)


class RansomState(StatesGroup):
    entering_amount = State()


# ─────────────────────────────────────────────────────────────────
# ASIRGA OLISH
# ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("prisoner:capture:"))
async def capture_lord(callback: CallbackQuery):
    """G'olib lord mag'lub lordni asirga oladi (100 askar evaziga)"""
    parts = callback.data.split(":")
    war_id           = int(parts[2])
    prisoner_user_id = int(parts[3])

    async with AsyncSessionFactory() as session:
        user_repo     = UserRepo(session)
        house_repo    = HouseRepo(session)
        prisoner_repo = PrisonerRepo(session)
        chronicle_repo = ChronicleRepo(session)

        captor = await user_repo.get_by_id(callback.from_user.id)
        if not captor or captor.role not in [RoleEnum.LORD, RoleEnum.HIGH_LORD]:
            await callback.answer("❌ Faqat lord asirga oladi.", show_alert=True)
            return

        captor_house = await house_repo.get_by_id(captor.house_id)
        if captor_house.total_soldiers < 100:
            await callback.answer("❌ 100 askar yetarli emas.", show_alert=True)
            return

        # Asir allaqachon olinganmi?
        existing = await prisoner_repo.get_by_prisoner_user(prisoner_user_id)
        if existing:
            await callback.answer("❌ Bu lord allaqachon asirda.", show_alert=True)
            return

        prisoner_user  = await user_repo.get_by_id(prisoner_user_id)
        if not prisoner_user:
            await callback.answer("❌ Lord topilmadi.", show_alert=True)
            return

        prisoner_house = await house_repo.get_by_id(prisoner_user.house_id)
        if not prisoner_house:
            await callback.answer("❌ Xonadon topilmadi.", show_alert=True)
            return

        # 100 askar sarflash
        await house_repo.update_military(captor_house.id, soldiers=-100)

        # Omonatni topish — omonatdagi resurslar himoyalangan
        from database.repositories import IronBankDepositRepo
        dep_repo  = IronBankDepositRepo(session)
        deposit   = await dep_repo.get_active(prisoner_house.id)

        deposited_gold      = deposit.gold      if deposit else 0
        deposited_soldiers  = deposit.soldiers  if deposit else 0
        deposited_dragons   = deposit.dragons   if deposit else 0
        deposited_scorpions = deposit.scorpions if deposit else 0

        # Transfer = mavjud - omonat
        transfer_gold      = max(0, prisoner_house.treasury      - deposited_gold)
        transfer_soldiers  = max(0, prisoner_house.total_soldiers - deposited_soldiers)
        transfer_dragons   = max(0, prisoner_house.total_dragons  - deposited_dragons)
        transfer_scorpions = max(0, prisoner_house.total_scorpions - deposited_scorpions)

        # Prisoner xonadondan ayirish
        await house_repo.update_treasury(prisoner_house.id, -transfer_gold)
        await house_repo.update_military(
            prisoner_house.id,
            soldiers=-transfer_soldiers,
            dragons=-transfer_dragons,
            scorpions=-transfer_scorpions,
        )
        # G'olib xonadonga qo'shish
        await house_repo.update_treasury(captor_house.id, transfer_gold)
        await house_repo.update_military(
            captor_house.id,
            soldiers=transfer_soldiers,
            dragons=transfer_dragons,
            scorpions=transfer_scorpions,
        )

        # Prisoner yozuvi yaratish
        prisoner = await prisoner_repo.create(prisoner_user_id, captor_house.id, war_id)

        # Chronicle
        text = format_chronicle(
            "lord_captured",
            captor=captor_house.name,
            prisoner=prisoner_user.full_name,
        )
        tg_id = await post_to_chronicle(callback.bot, text)
        await chronicle_repo.add("lord_captured", text,
                                  user_id=prisoner_user_id,
                                  house_id=captor_house.id,
                                  tg_msg_id=tg_id)

        # Asir lordga xabar
        try:
            await callback.bot.send_message(
                prisoner_user_id,
                f"🔗 <b>Siz asirga oldingiz!</b>\n\n"
                f"G'olib: <b>{captor_house.name}</b>\n"
                f"💰 Resurslaringiz ularga o'tdi:\n"
                f"🏅 {transfer_gold} oltin | 🗡️ {transfer_soldiers} askar | "
                f"🐉 {transfer_dragons} ajdar | 🏹 {transfer_scorpions} skorpion\n\n"
                f"Ozod bo'lish uchun ittifoqchilaringizdan yordam so'rang.",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Asirga xabar yuborishda xato: {e}")

    await callback.answer()
    await callback.message.answer(
        f"🔗 <b>Lord asirga olindi!</b>\n\n"
        f"👤 {prisoner_user.full_name}\n"
        f"💰 Qo'shildi: {transfer_gold} oltin | "
        f"{transfer_soldiers} askar | {transfer_dragons} ajdar | {transfer_scorpions} skorpion",
        parse_mode="HTML"
    )


@router.callback_query(F.data == "prisoner:skip")
async def capture_skip(callback: CallbackQuery):
    """Asirga olishdan voz kechish"""
    await callback.answer()
    await callback.message.answer("Asirga olishdan voz kechdingiz.")


# ─────────────────────────────────────────────────────────────────
# ASIRLAR PANELI
# ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "prisoner:list")
async def prisoner_list(callback: CallbackQuery):
    """G'olib xonadonning asirlar ro'yxati"""
    async with AsyncSessionFactory() as session:
        user_repo     = UserRepo(session)
        prisoner_repo = PrisonerRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)

        if not user or not user.house_id:
            await callback.answer("❌ Xonadoningiz yo'q.", show_alert=True)
            return

        prisoners = await prisoner_repo.get_active_for_house(user.house_id)

    if not prisoners:
        await callback.answer("Asirlar yo'q.", show_alert=True)
        return

    from keyboards.keyboards import prisoner_manage_keyboard
    text = "🔗 <b>ASIRLAR PANELI</b>\n\n"
    for p in prisoners:
        ransom_text = f"{p.ransom_amount:,} tanga" if p.ransom_amount else "Belgilanmagan"
        text += (
            f"👤 {p.prisoner_user.full_name}\n"
            f"💰 Tovon: {ransom_text}\n\n"
        )

    await callback.answer()
    await callback.message.answer(
        text,
        reply_markup=prisoner_manage_keyboard(prisoners[0].id) if len(prisoners) == 1 else None,
        parse_mode="HTML"
    )


# ─────────────────────────────────────────────────────────────────
# TOVON PULI BELGILASH
# ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("prisoner:ransom:"))
async def set_ransom_start(callback: CallbackQuery, state: FSMContext):
    """Tovon puli miqdorini kiritish"""
    prisoner_id = int(callback.data.split(":")[2])

    async with AsyncSessionFactory() as session:
        user_repo     = UserRepo(session)
        prisoner_repo = PrisonerRepo(session)
        user     = await user_repo.get_by_id(callback.from_user.id)
        prisoner = await prisoner_repo.get_by_id(prisoner_id)

        if not prisoner or prisoner.captor_house_id != user.house_id:
            await callback.answer("❌ Bu asir sizga tegishli emas.", show_alert=True)
            return

    await state.update_data(prisoner_id=prisoner_id)
    await state.set_state(RansomState.entering_amount)
    await callback.answer()
    await callback.message.answer(
        "💰 <b>Tovon puli miqdorini kiriting (tanga):</b>\n"
        "(0 kiriting — tovon bekor qilish)",
        parse_mode="HTML"
    )


@router.message(RansomState.entering_amount)
async def set_ransom_amount(message: Message, state: FSMContext):
    data = await state.get_data()
    prisoner_id = data["prisoner_id"]

    try:
        amount = int(message.text.strip())
        if amount < 0:
            raise ValueError
    except (ValueError, TypeError):
        await message.answer("❌ Musbat son kiriting.")
        return

    async with AsyncSessionFactory() as session:
        prisoner_repo = PrisonerRepo(session)
        prisoner_repo2 = PrisonerRepo(session)
        prisoner = await prisoner_repo.get_by_id(prisoner_id)
        if not prisoner:
            await message.answer("❌ Asir topilmadi.")
            await state.clear()
            return

        await prisoner_repo.set_ransom(prisoner_id, amount)

        # Asirga xabar
        if amount > 0:
            try:
                await message.bot.send_message(
                    prisoner.prisoner_user_id,
                    f"💰 <b>Tovon puli belgilandi!</b>\n\n"
                    f"Ozod bo'lish uchun: <b>{amount:,} tanga</b>\n"
                    f"Ittifoqchilaringizdan to'lashni so'rang.",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    await state.clear()
    if amount > 0:
        await message.answer(f"✅ Tovon puli: {amount:,} tanga belgilandi.")
    else:
        await message.answer("✅ Tovon puli bekor qilindi.")


# ─────────────────────────────────────────────────────────────────
# TOVON TO'LASH (ITTIFOQCHI TOMONIDAN)
# ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("prisoner:pay_ransom:"))
async def pay_ransom(callback: CallbackQuery):
    """Ittifoqchi asir lordning tovonini to'laydi"""
    prisoner_id = int(callback.data.split(":")[2])

    async with AsyncSessionFactory() as session:
        user_repo     = UserRepo(session)
        house_repo    = HouseRepo(session)
        prisoner_repo = PrisonerRepo(session)
        chronicle_repo = ChronicleRepo(session)

        user     = await user_repo.get_by_id(callback.from_user.id)
        prisoner = await prisoner_repo.get_by_id(prisoner_id)

        if not prisoner:
            await callback.answer("❌ Asir topilmadi.", show_alert=True)
            return

        if prisoner.status != PrisonerStatusEnum.CAPTURED:
            await callback.answer("❌ Bu asir allaqachon ozod yoki o'ldirilgan.", show_alert=True)
            return

        if prisoner.ransom_amount == 0:
            await callback.answer("❌ Tovon puli belgilanmagan.", show_alert=True)
            return

        payer_house = await house_repo.get_by_id(user.house_id)
        if payer_house.treasury < prisoner.ransom_amount:
            await callback.answer(
                f"❌ Yetarli oltin yo'q. Kerak: {prisoner.ransom_amount:,} tanga.",
                show_alert=True
            )
            return

        # To'lov
        await house_repo.update_treasury(payer_house.id, -prisoner.ransom_amount)
        await house_repo.update_treasury(prisoner.captor_house_id, prisoner.ransom_amount)
        await prisoner_repo.free(prisoner_id)

        captor_house = await house_repo.get_by_id(prisoner.captor_house_id)

        # Chronicle
        text = format_chronicle(
            "lord_ransomed",
            payer=payer_house.name,
            prisoner=prisoner.prisoner_user.full_name,
            amount=prisoner.ransom_amount,
        )
        tg_id = await post_to_chronicle(callback.bot, text)
        await chronicle_repo.add("lord_freed", text,
                                  user_id=prisoner.prisoner_user_id,
                                  house_id=prisoner.captor_house_id,
                                  tg_msg_id=tg_id)

        # Asirga xabar
        try:
            await callback.bot.send_message(
                prisoner.prisoner_user_id,
                f"🕊️ <b>Siz ozod bo'ldingiz!</b>\n\n"
                f"{payer_house.name} xonadoni {prisoner.ransom_amount:,} tanga to'lab ozod qildi.",
                parse_mode="HTML"
            )
        except Exception:
            pass

        # Asir xonadon lordiga xabar
        if captor_house and captor_house.lord_id:
            try:
                await callback.bot.send_message(
                    captor_house.lord_id,
                    f"💰 <b>Tovon to'landi!</b>\n\n"
                    f"{payer_house.name} xonadoni {prisoner.ransom_amount:,} tanga to'ladi.\n"
                    f"{prisoner.prisoner_user.full_name} lord ozod bo'ldi.",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    await callback.answer()
    await callback.message.answer(
        f"✅ <b>Tovon to'landi!</b>\n"
        f"💰 {prisoner.ransom_amount:,} tanga | {prisoner.prisoner_user.full_name} ozod bo'ldi.",
        parse_mode="HTML"
    )


# ─────────────────────────────────────────────────────────────────
# OZOD QILISH (G'OLIB TOMONIDAN — BEPUl)
# ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("prisoner:free:"))
async def free_prisoner(callback: CallbackQuery):
    """G'olib lord asirni bepul ozod qiladi"""
    prisoner_id = int(callback.data.split(":")[2])

    async with AsyncSessionFactory() as session:
        user_repo     = UserRepo(session)
        prisoner_repo = PrisonerRepo(session)
        chronicle_repo = ChronicleRepo(session)

        user     = await user_repo.get_by_id(callback.from_user.id)
        prisoner = await prisoner_repo.get_by_id(prisoner_id)

        if not prisoner:
            await callback.answer("❌ Asir topilmadi.", show_alert=True)
            return

        if prisoner.captor_house_id != user.house_id:
            await callback.answer("❌ Bu asir sizga tegishli emas.", show_alert=True)
            return

        await prisoner_repo.free(prisoner_id)

        text = format_chronicle(
            "lord_freed",
            prisoner=prisoner.prisoner_user.full_name,
        )
        tg_id = await post_to_chronicle(callback.bot, text)
        await chronicle_repo.add("lord_freed", text,
                                  user_id=prisoner.prisoner_user_id,
                                  house_id=prisoner.captor_house_id,
                                  tg_msg_id=tg_id)

        try:
            await callback.bot.send_message(
                prisoner.prisoner_user_id,
                "🕊️ <b>Siz ozod bo'ldingiz!</b>\n\nG'olib lord sizi bepul ozod qildi.",
                parse_mode="HTML"
            )
        except Exception:
            pass

    await callback.answer()
    await callback.message.answer(
        f"🕊️ {prisoner.prisoner_user.full_name} lord ozod qilindi.",
        parse_mode="HTML"
    )


# ─────────────────────────────────────────────────────────────────
# O'LDIRISH
# ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("prisoner:execute:"))
async def execute_prisoner_handler(callback: CallbackQuery):
    """G'olib lord asirni o'ldiradi — executed_lord_flag=True, barcha resurslar o'tadi"""
    prisoner_id = int(callback.data.split(":")[2])

    async with AsyncSessionFactory() as session:
        user_repo     = UserRepo(session)
        house_repo    = HouseRepo(session)
        prisoner_repo = PrisonerRepo(session)
        chronicle_repo = ChronicleRepo(session)

        user     = await user_repo.get_by_id(callback.from_user.id)
        prisoner = await prisoner_repo.get_by_id(prisoner_id)

        if not prisoner:
            await callback.answer("❌ Asir topilmadi.", show_alert=True)
            return

        if prisoner.captor_house_id != user.house_id:
            await callback.answer("❌ Bu asir sizga tegishli emas.", show_alert=True)
            return

        captor_house   = await house_repo.get_by_id(prisoner.captor_house_id)
        prisoner_house = await house_repo.get_by_id(prisoner.prisoner_user.house_id)

        # Barcha resurslar transfer (omonat ham ichida — o'ldirishda himoya yo'q)
        transfer_gold      = prisoner_house.treasury
        transfer_soldiers  = prisoner_house.total_soldiers
        transfer_dragons   = prisoner_house.total_dragons
        transfer_scorpions = prisoner_house.total_scorpions

        await house_repo.update_treasury(prisoner_house.id, -transfer_gold)
        await house_repo.update_military(
            prisoner_house.id,
            soldiers=-transfer_soldiers,
            dragons=-transfer_dragons,
            scorpions=-transfer_scorpions,
        )
        await house_repo.update_treasury(captor_house.id, transfer_gold)
        await house_repo.update_military(
            captor_house.id,
            soldiers=transfer_soldiers,
            dragons=transfer_dragons,
            scorpions=transfer_scorpions,
        )

        # executed_lord_flag = True → barcha xonadon bu lordga urush ocha oladi
        from sqlalchemy import update as sa_update
        from database.models import War
        await session.execute(
            sa_update(War)
            .where(War.id == prisoner.war_id)
            .values(executed_lord_flag=True)
        )
        await session.commit()

        await prisoner_repo.execute_prisoner(prisoner_id)

        # Chronicle
        text = format_chronicle(
            "lord_executed",
            captor=captor_house.name,
            prisoner=prisoner.prisoner_user.full_name,
        )
        tg_id = await post_to_chronicle(callback.bot, text)
        await chronicle_repo.add("lord_executed", text,
                                  user_id=prisoner.prisoner_user_id,
                                  house_id=captor_house.id,
                                  tg_msg_id=tg_id)

        # Asirga xabar (agar bot yubora olsa)
        try:
            await callback.bot.send_message(
                prisoner.prisoner_user_id,
                f"💀 <b>Siz o'ldirilgansiz!</b>\n\n"
                f"{captor_house.name} xonadoni sizni o'ldirdi.\n"
                f"Barcha resurslaringiz ularga o'tdi.\n\n"
                f"⚠️ Endi barcha xonadon sizga urush ochishi mumkin.",
                parse_mode="HTML"
            )
        except Exception:
            pass

    await callback.answer()
    await callback.message.answer(
        f"💀 <b>{prisoner.prisoner_user.full_name} lord o'ldirildi!</b>\n\n"
        f"💰 Qo'shildi: {transfer_gold} oltin | {transfer_soldiers} askar | "
        f"{transfer_dragons} ajdar | {transfer_scorpions} skorpion\n\n"
        f"⚠️ Xronikaga yozildi — endi barcha xonadon bu lordga urush ocha oladi.",
        parse_mode="HTML"
    )
