from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.engine import AsyncSessionFactory
from database.repositories import UserRepo, HouseRepo, AllianceRepo
from database.models import RoleEnum, WarStatusEnum, WarAllySupport
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from database.models import War
import logging

router = Router()
logger = logging.getLogger(__name__)


class AllySupportState(StatesGroup):
    entering_soldiers = State()


def ally_support_keyboard(war_id: int, side: str) -> object:
    """Ittifoqchi uchun yordam tanlash klaviaturasi"""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⚔️ Jangga qo'shilish (barcha resurs bilan)",
        callback_data=f"ally:full:{war_id}:{side}"
    )
    builder.button(
        text="🗡️ Yordam yuborish (askar miqdori tanlash)",
        callback_data=f"ally:soldiers:{war_id}:{side}"
    )
    builder.button(
        text="❌ Rad etish",
        callback_data=f"ally:decline:{war_id}:{side}"
    )
    builder.adjust(1)
    return builder.as_markup()


async def notify_allies(bot, war, house, side: str):
    """
    Xonadon ittifoqchilariga urush haqida xabar yuboradi
    va yordam so'rash tugmalarini ko'rsatadi.
    side = "attacker" | "defender"
    """
    async with AsyncSessionFactory() as session:
        alliance_repo = AllianceRepo(session)
        house_repo = HouseRepo(session)

        alliances = await alliance_repo.get_all_active_for_house(house.id)
        if not alliances:
            return

        enemy = war.defender if side == "attacker" else war.attacker
        role_text = "hujumchi" if side == "attacker" else "mudofaachi"

        for alliance in alliances:
            ally_id = alliance.house2_id if alliance.house1_id == house.id else alliance.house1_id
            ally_house = await house_repo.get_by_id(ally_id)
            if not ally_house or not ally_house.lord_id:
                continue

            # Allaqachon qo'shilganmi tekshirish
            existing = await session.execute(
                select(WarAllySupport).where(
                    WarAllySupport.war_id == war.id,
                    WarAllySupport.ally_house_id == ally_id,
                )
            )
            if existing.scalar_one_or_none():
                continue

            try:
                await bot.send_message(
                    ally_house.lord_id,
                    f"🤝 <b>ITTIFOQCHI YORDAM SO'RAMOQDA!</b>\n\n"
                    f"<b>{house.name}</b> xonadoni ({role_text}) "
                    f"<b>{enemy.name}</b> bilan urushda sizdan yordam so'ramoqda.\n\n"
                    f"Qanday yordam berasiz?",
                    reply_markup=ally_support_keyboard(war.id, side),
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"Ittifoqchiga xabar yuborishda xato: {e}")


@router.callback_query(F.data.startswith("ally:full:"))
async def ally_join_full(callback: CallbackQuery):
    """Ittifoqchi to'liq resurs bilan qo'shiladi"""
    _, _, war_id, side = callback.data.split(":")
    war_id = int(war_id)

    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)
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

        # Ittifoq buzilishi tekshiruvi
        # Agar side=defender, lekin war.attacker ittifoqchisi bo'lsa → ittifoq buziladi
        enemy_house_id = war.attacker_house_id if side == "defender" else war.defender_house_id
        alliance_repo = AllianceRepo(session)
        enemy_alliance = await alliance_repo.get_active(user.house_id, enemy_house_id)

        if enemy_alliance:
            # Ittifoqni buzish
            enemy_house = await house_repo.get_by_id(enemy_house_id)
            await alliance_repo.break_alliance(enemy_alliance.id)
            logger.info(f"Ittifoq buzildi: {house.name} vs {enemy_house.name}")

            # Raqibga xabar
            if enemy_house and enemy_house.lord_id:
                try:
                    await callback.bot.send_message(
                        enemy_house.lord_id,
                        f"💔 <b>ITTIFOQ BUZILDI!</b>\n\n"
                        f"<b>{house.name}</b> xonadoni sizga qarshi urushga qo'shildi!\n"
                        f"Ittifoqingiz avtomatik bekor qilindi.",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

        # Yordam yozish
        support = WarAllySupport(
            war_id=war_id,
            ally_house_id=user.house_id,
            side=side,
            join_type="full",
            soldiers=house.total_soldiers,
            dragons=house.total_dragons,
            scorpions=house.total_scorpions,
        )
        session.add(support)
        await session.commit()

        # Asosiy tomonga xabar
        main_house = war.attacker if side == "attacker" else war.defender
        if main_house.lord_id:
            try:
                await callback.bot.send_message(
                    main_house.lord_id,
                    f"🤝 <b>{house.name}</b> jangga qo'shildi!\n"
                    f"🗡️ +{house.total_soldiers} askar | "
                    f"🐉 +{house.total_dragons} ajdar | "
                    f"🏹 +{house.total_scorpions} skorpion",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    await callback.answer()
    await callback.message.edit_text(
        f"⚔️ <b>Jangga qo'shildingiz!</b>\n\n"
        f"Barcha resurslaringiz urushda ishtirok etadi.\n"
        f"G'alaba bo'lsa resurslaringiz qaytadi, "
        f"mag'lubiyatda yo'qoladi.",
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("ally:soldiers:"))
async def ally_send_soldiers_start(callback: CallbackQuery, state: FSMContext):
    """Yordam yuborish — miqdor kiritish"""
    _, _, war_id, side = callback.data.split(":")

    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)

        if not user or not user.house_id:
            await callback.answer("❌ Xonadoningiz yo'q.", show_alert=True)
            return

        house = await house_repo.get_by_id(user.house_id)

        await state.set_state(AllySupportState.entering_soldiers)
        await state.update_data(war_id=int(war_id), side=side, house_id=user.house_id)

    await callback.answer()
    await callback.message.edit_text(
        f"🗡️ <b>Nechta askar yubormoqchisiz?</b>\n\n"
        f"Sizda: {house.total_soldiers} askar mavjud.\n"
        f"Raqam kiriting (1 — {house.total_soldiers}):",
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
        alliance_repo = AllianceRepo(session)
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

        # Ittifoq buzilishi tekshiruvi
        enemy_house_id = war.attacker_house_id if side == "defender" else war.defender_house_id
        enemy_alliance = await alliance_repo.get_active(user.house_id, enemy_house_id)

        if enemy_alliance:
            enemy_house = await house_repo.get_by_id(enemy_house_id)
            await alliance_repo.break_alliance(enemy_alliance.id)

            if enemy_house and enemy_house.lord_id:
                try:
                    await message.bot.send_message(
                        enemy_house.lord_id,
                        f"💔 <b>ITTIFOQ BUZILDI!</b>\n\n"
                        f"<b>{house.name}</b> sizga qarshi urushga askar yubordi!\n"
                        f"Ittifoqingiz avtomatik bekor qilindi.",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

        # Yordam yozish
        support = WarAllySupport(
            war_id=war_id,
            ally_house_id=user.house_id,
            side=side,
            join_type="soldiers",
            soldiers=amount,
            dragons=0,
            scorpions=0,
        )
        session.add(support)
        await session.commit()

        # Asosiy tomonga xabar
        main_house = war.attacker if side == "attacker" else war.defender
        if main_house.lord_id:
            try:
                await message.bot.send_message(
                    main_house.lord_id,
                    f"🤝 <b>{house.name}</b> {amount} askar yubordi!\n"
                    f"G'alaba bo'lsa askarlar qaytadi.",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    await state.clear()
    await message.answer(
        f"✅ <b>{amount} askar yuborildi!</b>\n\n"
        f"G'alaba bo'lsa askarlaringiz to'liq qaytadi.\n"
        f"Mag'lubiyatda yo'qoladi.",
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("ally:decline:"))
async def ally_decline(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("❌ Yordam berishdan voz kechdingiz.")
