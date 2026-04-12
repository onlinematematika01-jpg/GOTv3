from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.engine import AsyncSessionFactory
from database.repositories import UserRepo, HouseRepo, WarRepo, AllianceGroupRepo
from database.models import RoleEnum, WarStatusEnum, WarAllySupport
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from database.models import War
import logging

router = Router()
logger = logging.getLogger(__name__)


class AllySupportState(StatesGroup):
    entering_soldiers = State()
    entering_gold = State()


def ally_support_keyboard(war_id: int, side: str) -> object:
    """Ittifoqchi uchun yordam tanlash klaviaturasi"""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⚔️ To'liq qo'shilish (barcha askar + skorpion)",
        callback_data=f"ally:full:{war_id}:{side}"
    )
    builder.button(
        text="🗡️ Askar yuborish (miqdor tanlash)",
        callback_data=f"ally:soldiers:{war_id}:{side}"
    )
    builder.button(
        text="💰 Oltin yuborish (miqdor tanlash)",
        callback_data=f"ally:gold:{war_id}:{side}"
    )
    builder.button(
        text="❌ Rad etish",
        callback_data=f"ally:decline:{war_id}:{side}"
    )
    builder.adjust(1)
    return builder.as_markup()


async def notify_allies(bot, war, house, side: str):
    """
    Xonadonning ITTIFOQ GURUHI a'zolariga urush haqida xabar yuboradi.
    Faqat bir guruhda bo'lgan xonadonlar xabardor qilinadi.
    side = "attacker" | "defender"
    """
    house_id = house.id if hasattr(house, "id") else house
    war_id = war.id

    async with AsyncSessionFactory() as session:
        group_repo = AllianceGroupRepo(session)
        house_repo = HouseRepo(session)
        war_repo = WarRepo(session)

        # Urushni qayta yuklaymiz (detached object muammosini oldini olish)
        war_result = await session.execute(select(War).where(War.id == war_id))
        war_obj = war_result.scalar_one_or_none()
        if not war_obj:
            return

        # Xonadonning ittifoq guruhini topamiz
        group = await group_repo.get_house_active_group(house_id)
        if not group or len(group.members) <= 1:
            # Guruhda emas yoki yakka — hech kimga xabar yo'q
            return

        enemy_house_id = (
            war_obj.defender_house_id if side == "attacker"
            else war_obj.attacker_house_id
        )
        enemy = await house_repo.get_by_id(enemy_house_id)
        my_house = await house_repo.get_by_id(house_id)
        if not enemy or not my_house:
            return

        role_text = "hujumchi" if side == "attacker" else "mudofaachi"

        # Guruh a'zolariga (o'zimizdan tashqari) xabar yuboramiz
        for member in group.members:
            ally_id = member.house_id
            if ally_id == house_id:
                continue

            ally_house = await house_repo.get_by_id(ally_id)
            if not ally_house or not ally_house.lord_id:
                continue

            # Allaqachon qo'shilganmi
            existing = await session.execute(
                select(WarAllySupport).where(
                    WarAllySupport.war_id == war_obj.id,
                    WarAllySupport.ally_house_id == ally_id,
                )
            )
            if existing.scalar_one_or_none():
                continue

            # O'zi urushda bo'lsa — o'tkazib yuboriladi
            own_war = await war_repo.get_active_war(ally_id)
            if own_war:
                continue

            try:
                await bot.send_message(
                    ally_house.lord_id,
                    f"🏰 <b>ITTIFOQ GURUHI YORDAM SO'RAMOQDA!</b>\n\n"
                    f"«<b>{group.name}</b>» guruhingiz a'zosi\n"
                    f"<b>{my_house.name}</b> ({role_text}) "
                    f"<b>{enemy.name}</b> bilan urushda!\n\n"
                    f"Guruh sifatida qo'llab-quvvatlaysizmi?",
                    reply_markup=ally_support_keyboard(war_obj.id, side),
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"Guruh a'zosiga xabar yuborishda xato ({ally_id}): {e}")


async def _check_group_ally_conflict(session, user_house_id: int, enemy_house_id: int) -> bool:
    """
    Agar user guruhida bo'lsa va guruh a'zolaridan biri dushman bilan
    bir guruhda bo'lsa — xato. Hozircha bunday cheklov qo'yilmagan,
    lekin kelajakda kerak bo'lsa shu funksiyadan foydalanamiz.
    """
    return False


@router.callback_query(F.data.startswith("ally:full:"))
async def ally_join_full(callback: CallbackQuery):
    """Ittifoqchi to'liq resurs bilan qo'shiladi"""
    _, _, war_id, side = callback.data.split(":")
    war_id = int(war_id)

    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)
        group_repo = AllianceGroupRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)

        if not user or user.role not in [RoleEnum.LORD, RoleEnum.HIGH_LORD]:
            await callback.answer("❌ Faqat Lord qaror qabul qila oladi.", show_alert=True)
            return

        if not user.house_id:
            await callback.answer("❌ Xonadoningiz yo'q.", show_alert=True)
            return

        house = await house_repo.get_by_id(user.house_id)
        war_result = await session.execute(
            select(War).where(War.id == war_id)
            .options(selectinload(War.attacker), selectinload(War.defender))
        )
        war = war_result.scalar_one_or_none()

        if not war or war.status not in [WarStatusEnum.GRACE_PERIOD, WarStatusEnum.FIGHTING]:
            await callback.answer("❌ Bu urush allaqachon tugagan.", show_alert=True)
            return

        # O'zi urushda bo'lsa — yordamga qo'shila olmaydi
        war_repo = WarRepo(session)
        own_war = await war_repo.get_active_war(user.house_id)
        if own_war and own_war.id != war_id:
            await callback.answer(
                "❌ Siz hozir urushda bo'lganingiz uchun yordam bera olmaysiz.",
                show_alert=True
            )
            return

        # Allaqachon qo'shilganmi
        existing = await session.execute(
            select(WarAllySupport).where(
                WarAllySupport.war_id == war_id,
                WarAllySupport.ally_house_id == user.house_id,
            )
        )
        if existing.scalar_one_or_none():
            await callback.answer("❌ Siz allaqachon bu urushga qo'shilgansiz.", show_alert=True)
            return

        # Guruh tekshiruvi — faqat bir guruh a'zosi yordam bera oladi
        # Urush e'lon qilgan tomoning guruhiga a'zo bo'lish shart
        main_house_id = war.attacker_house_id if side == "attacker" else war.defender_house_id
        ally_group = await group_repo.get_house_active_group(user.house_id)
        main_group = await group_repo.get_house_active_group(main_house_id)

        if not ally_group or not main_group or ally_group.id != main_group.id:
            await callback.answer(
                "❌ Faqat bir xil ittifoq guruhidagi xonadonlar yordam bera oladi.",
                show_alert=True
            )
            return

        support = WarAllySupport(
            war_id=war_id,
            ally_house_id=user.house_id,
            side=side,
            join_type="full",
            soldiers=house.total_soldiers,
            dragons=0,
            scorpions=house.total_scorpions,
            gold=0,
        )
        session.add(support)
        await session.commit()

        main_house = war.attacker if side == "attacker" else war.defender
        if main_house.lord_id:
            try:
                await callback.bot.send_message(
                    main_house.lord_id,
                    f"🤝 <b>«{ally_group.name}»</b> guruhidan\n"
                    f"<b>{house.name}</b> jangga qo'shildi!\n"
                    f"🗡️ +{house.total_soldiers} askar | 🏹 +{house.total_scorpions} skorpion",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        from utils.chronicle import post_to_chronicle, post_war_power_update
        side_text = "hujumchi" if side == "attacker" else "mudofaachi"
        ally_text = (
            f"🤝 <b>ITTIFOQ GURUH A'ZOSI QO'SHILDI!</b>\n\n"
            f"<b>{house.name}</b> [{ally_group.name}] → "
            f"<b>{main_house.name}</b> ({side_text}) tomoniga qo'shildi!\n"
            f"🗡️ {house.total_soldiers} askar | 🏹 {house.total_scorpions} skorpion"
        )
        try:
            await post_to_chronicle(callback.bot, ally_text)
            await post_war_power_update(callback.bot, war_id)
        except Exception as e:
            logger.warning(f"Kanal xabari (ally full) xatosi: {e}")

    await callback.answer()
    await callback.message.edit_text(
        f"⚔️ <b>Jangga qo'shildingiz!</b>\n\n"
        f"Askar va skorpionlaringiz urushda ishtirok etadi.\n"
        f"⚠️ Ajdarlar urushga yuborilmaydi.\n"
        f"G'alaba bo'lsa resurslaringiz qaytadi, mag'lubiyatda yo'qoladi.",
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("ally:soldiers:"))
async def ally_send_soldiers_start(callback: CallbackQuery, state: FSMContext):
    """Yordam yuborish — askar miqdori kiritish"""
    _, _, war_id, side = callback.data.split(":")

    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)
        group_repo = AllianceGroupRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)

        if not user or not user.house_id:
            await callback.answer("❌ Xonadoningiz yo'q.", show_alert=True)
            return

        # Guruh tekshiruvi
        war_result = await session.execute(select(War).where(War.id == int(war_id)))
        war = war_result.scalar_one_or_none()
        if not war:
            await callback.answer("❌ Urush topilmadi.", show_alert=True)
            return

        main_house_id = war.attacker_house_id if side == "attacker" else war.defender_house_id
        ally_group = await group_repo.get_house_active_group(user.house_id)
        main_group = await group_repo.get_house_active_group(main_house_id)

        if not ally_group or not main_group or ally_group.id != main_group.id:
            await callback.answer(
                "❌ Faqat bir xil ittifoq guruhidagi xonadonlar yordam bera oladi.",
                show_alert=True
            )
            return

        house = await house_repo.get_by_id(user.house_id)
        await state.set_state(AllySupportState.entering_soldiers)
        await state.update_data(war_id=int(war_id), side=side, house_id=user.house_id)
        soldiers = house.total_soldiers

    await callback.answer()
    await callback.message.edit_text(
        f"🗡️ <b>Nechta askar yubormoqchisiz?</b>\n\n"
        f"Sizda: {soldiers} askar mavjud.\n"
        f"Raqam kiriting (1 — {soldiers}):",
        parse_mode="HTML"
    )


@router.message(AllySupportState.entering_soldiers)
async def ally_send_soldiers_confirm(message: Message, state: FSMContext):
    data = await state.get_data()
    war_id = data["war_id"]
    side = data["side"]

    try:
        amount = int(message.text.strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Iltimos, musbat son kiriting.")
        return

    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)
        group_repo = AllianceGroupRepo(session)
        user = await user_repo.get_by_id(message.from_user.id)
        house = await house_repo.get_by_id(user.house_id)

        if amount > house.total_soldiers:
            await message.answer(f"❌ Sizda faqat {house.total_soldiers} askar bor.")
            return

        war_result = await session.execute(
            select(War).where(War.id == war_id)
            .options(selectinload(War.attacker), selectinload(War.defender))
        )
        war = war_result.scalar_one_or_none()
        if not war or war.status not in [WarStatusEnum.GRACE_PERIOD, WarStatusEnum.FIGHTING]:
            await message.answer("❌ Bu urush allaqachon tugagan.")
            await state.clear()
            return

        war_repo = WarRepo(session)
        own_war = await war_repo.get_active_war(user.house_id)
        if own_war and own_war.id != war_id:
            await message.answer("❌ Siz hozir urushda bo'lganingiz uchun yordam bera olmaysiz.")
            await state.clear()
            return

        main_house_id = war.attacker_house_id if side == "attacker" else war.defender_house_id
        ally_group = await group_repo.get_house_active_group(user.house_id)
        main_group = await group_repo.get_house_active_group(main_house_id)
        if not ally_group or not main_group or ally_group.id != main_group.id:
            await message.answer("❌ Faqat bir xil ittifoq guruhidagi xonadonlar yordam bera oladi.")
            await state.clear()
            return

        support = WarAllySupport(
            war_id=war_id,
            ally_house_id=user.house_id,
            side=side,
            join_type="soldiers",
            soldiers=amount,
            dragons=0,
            scorpions=0,
            gold=0,
        )
        session.add(support)
        await session.commit()

        main_house = war.attacker if side == "attacker" else war.defender
        group_name = ally_group.name
        if main_house.lord_id:
            try:
                await message.bot.send_message(
                    main_house.lord_id,
                    f"🤝 <b>«{group_name}»</b> guruhidan\n"
                    f"<b>{house.name}</b> {amount} askar yubordi!",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        from utils.chronicle import post_to_chronicle, post_war_power_update
        side_text = "hujumchi" if side == "attacker" else "mudofaachi"
        ally_text = (
            f"🤝 <b>GURUH A'ZOSI ASKAR YUBORDI!</b>\n\n"
            f"<b>{house.name}</b> [{group_name}] → "
            f"<b>{main_house.name}</b> ({side_text}) tomonga\n"
            f"🗡️ {amount} askar yubordi"
        )
        try:
            await post_to_chronicle(message.bot, ally_text)
            await post_war_power_update(message.bot, war_id)
        except Exception as e:
            logger.warning(f"Kanal xabari (ally soldiers) xatosi: {e}")

    await state.clear()
    await message.answer(
        f"✅ <b>{amount} askar yuborildi!</b>\n\n"
        f"G'alaba bo'lsa askarlaringiz to'liq qaytadi.\n"
        f"Mag'lubiyatda yo'qoladi.",
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("ally:gold:"))
async def ally_send_gold_start(callback: CallbackQuery, state: FSMContext):
    """Oltin yuborish — miqdor kiritish"""
    _, _, war_id, side = callback.data.split(":")

    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)
        group_repo = AllianceGroupRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)

        if not user or not user.house_id:
            await callback.answer("❌ Xonadoningiz yo'q.", show_alert=True)
            return

        if user.role not in [RoleEnum.LORD, RoleEnum.HIGH_LORD]:
            await callback.answer("❌ Faqat Lord qaror qabul qila oladi.", show_alert=True)
            return

        # Guruh tekshiruvi
        war_result = await session.execute(select(War).where(War.id == int(war_id)))
        war = war_result.scalar_one_or_none()
        if not war:
            await callback.answer("❌ Urush topilmadi.", show_alert=True)
            return

        main_house_id = war.attacker_house_id if side == "attacker" else war.defender_house_id
        ally_group = await group_repo.get_house_active_group(user.house_id)
        main_group = await group_repo.get_house_active_group(main_house_id)

        if not ally_group or not main_group or ally_group.id != main_group.id:
            await callback.answer(
                "❌ Faqat bir xil ittifoq guruhidagi xonadonlar yordam bera oladi.",
                show_alert=True
            )
            return

        house = await house_repo.get_by_id(user.house_id)
        if house.treasury <= 0:
            await callback.answer("❌ Xazinangizda oltin yo'q.", show_alert=True)
            return

        await state.set_state(AllySupportState.entering_gold)
        await state.update_data(war_id=int(war_id), side=side, house_id=user.house_id)
        treasury = house.treasury

    await callback.answer()
    await callback.message.edit_text(
        f"💰 <b>Necha oltin yubormoqchisiz?</b>\n\n"
        f"Xazinada: {treasury} oltin mavjud.\n"
        f"Raqam kiriting (1 — {treasury}):",
        parse_mode="HTML"
    )


@router.message(AllySupportState.entering_gold)
async def ally_send_gold_confirm(message: Message, state: FSMContext):
    data = await state.get_data()
    war_id = data["war_id"]
    side = data["side"]

    try:
        amount = int(message.text.strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Iltimos, musbat son kiriting.")
        return

    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)
        group_repo = AllianceGroupRepo(session)
        user = await user_repo.get_by_id(message.from_user.id)
        house = await house_repo.get_by_id(user.house_id)

        if amount > house.treasury:
            await message.answer(f"❌ Xazinada faqat {house.treasury} oltin bor.")
            return

        war_result = await session.execute(
            select(War).where(War.id == war_id)
            .options(selectinload(War.attacker), selectinload(War.defender))
        )
        war = war_result.scalar_one_or_none()
        if not war or war.status not in [WarStatusEnum.GRACE_PERIOD, WarStatusEnum.FIGHTING]:
            await message.answer("❌ Bu urush allaqachon tugagan.")
            await state.clear()
            return

        war_repo = WarRepo(session)
        own_war = await war_repo.get_active_war(user.house_id)
        if own_war and own_war.id != war_id:
            await message.answer("❌ Siz hozir urushda bo'lganingiz uchun yordam bera olmaysiz.")
            await state.clear()
            return

        main_house_id = war.attacker_house_id if side == "attacker" else war.defender_house_id
        ally_group = await group_repo.get_house_active_group(user.house_id)
        main_group = await group_repo.get_house_active_group(main_house_id)
        if not ally_group or not main_group or ally_group.id != main_group.id:
            await message.answer("❌ Faqat bir xil ittifoq guruhidagi xonadonlar yordam bera oladi.")
            await state.clear()
            return

        await house_repo.update_treasury(house.id, -amount)
        main_house = war.attacker if side == "attacker" else war.defender
        await house_repo.update_treasury(main_house.id, amount)

        support = WarAllySupport(
            war_id=war_id,
            ally_house_id=user.house_id,
            side=side,
            join_type="gold",
            soldiers=0,
            dragons=0,
            scorpions=0,
            gold=amount,
        )
        session.add(support)
        await session.commit()

        group_name = ally_group.name
        if main_house.lord_id:
            try:
                await message.bot.send_message(
                    main_house.lord_id,
                    f"🤝 <b>«{group_name}»</b> guruhidan\n"
                    f"<b>{house.name}</b> {amount} oltin yubordi!\n"
                    f"💰 Xazinangizga qo'shildi.",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        from utils.chronicle import post_to_chronicle, post_war_power_update
        side_text = "hujumchi" if side == "attacker" else "mudofaachi"
        ally_text = (
            f"💰 <b>GURUH A'ZOSI OLTIN YUBORDI!</b>\n\n"
            f"<b>{house.name}</b> [{group_name}] → "
            f"<b>{main_house.name}</b> ({side_text}) tomonga\n"
            f"💰 {amount} oltin yubordi"
        )
        try:
            await post_to_chronicle(message.bot, ally_text)
            await post_war_power_update(message.bot, war_id)
        except Exception as e:
            logger.warning(f"Kanal xabari (ally gold) xatosi: {e}")

    await state.clear()
    await message.answer(
        f"✅ <b>{amount} oltin yuborildi!</b>\n\n"
        f"Oltin ittifoqchingiz xazinasiga darhol o'tkazildi.",
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("ally:decline:"))
async def ally_decline(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("❌ Yordam berishdan voz kechdingiz.")
