from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from datetime import datetime, timedelta
from database.engine import AsyncSessionFactory
from database.repositories import UserRepo, HouseRepo, WarRepo, AllianceRepo, ChronicleRepo
from database.models import RoleEnum, WarStatusEnum
from keyboards import war_menu_keyboard, house_list_keyboard, surrender_or_fight_keyboard
from utils.battle import calculate_battle, calculate_surrender_loot
from utils.chronicle import post_to_chronicle, format_chronicle
from config.settings import settings
from sqlalchemy import update
from database.models import User, House
import logging

router = Router()
logger = logging.getLogger(__name__)


class WarState(StatesGroup):
    selecting_target = State()


def is_war_time() -> bool:
    now = datetime.utcnow()
    local_hour = (now.hour + 5) % 24
    return settings.WAR_START_HOUR <= local_hour < settings.WAR_END_HOUR


def can_declare_war() -> bool:
    now = datetime.utcnow()
    local_hour = (now.hour + 5) % 24
    return settings.WAR_START_HOUR <= local_hour < settings.WAR_DECLARE_DEADLINE


@router.message(F.text == "⚔️ Urush")
async def war_menu(message: Message):
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        war_repo = WarRepo(session)
        user = await user_repo.get_by_id(message.from_user.id)

        if not user:
            await message.answer("❌ Avval /start bosing.")
            return

        is_lord = user.role in [RoleEnum.LORD, RoleEnum.HIGH_LORD, RoleEnum.ADMIN]
        active_war = None
        if user.house_id:
            active_war = await war_repo.get_active_war(user.house_id)

        war_time_text = "✅ Urush vaqti" if is_war_time() else "❌ Urush vaqti emas (19:00–23:00)"

        text = (
            "⚔️ <b>URUSH MARKAZI</b>\n\n"
            f"🕰️ {war_time_text}\n\n"
        )

        if active_war:
            other = active_war.defender if active_war.attacker_house_id == user.house_id else active_war.attacker
            text += (
                f"🔥 <b>Faol urush:</b> {other.name}\n"
                f"📊 Holat: {active_war.status.value}\n"
            )
            if active_war.grace_ends_at:
                remaining = active_war.grace_ends_at - datetime.utcnow()
                if remaining.total_seconds() > 0:
                    mins = int(remaining.total_seconds() // 60)
                    text += f"⏳ Grace Period qoldi: {mins} daqiqa\n"

        await message.answer(
            text,
            reply_markup=war_menu_keyboard(is_lord, bool(active_war)),
            parse_mode="HTML"
        )


@router.callback_query(F.data == "war:declare")
async def declare_war_start(callback: CallbackQuery, state: FSMContext):
    if not can_declare_war():
        await callback.answer("❌ Urush e'lon qilish vaqti emas! (19:00–22:00)", show_alert=True)
        return

    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        war_repo = WarRepo(session)
        house_repo = HouseRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)

        if not user or user.role not in [RoleEnum.LORD, RoleEnum.HIGH_LORD, RoleEnum.ADMIN]:
            await callback.answer("❌ Faqat Lordlar urush e'lon qila oladi.", show_alert=True)
            return

        if not user.house_id:
            await callback.answer("❌ Xonadoningiz yo'q.", show_alert=True)
            return

        active_war = await war_repo.get_active_war(user.house_id)
        if active_war:
            await callback.answer("❌ Allaqachon faol urush mavjud.", show_alert=True)
            return

        all_houses = await house_repo.get_all()
        targets = [h for h in all_houses if h.id != user.house_id]

        await state.set_state(WarState.selecting_target)
        await state.update_data(attacker_house_id=user.house_id)

        await callback.answer()
        await callback.message.answer(
            "🎯 <b>Hujum maqsadini tanlang:</b>",
            reply_markup=house_list_keyboard(targets, "war:target"),
            parse_mode="HTML"
        )


@router.callback_query(WarState.selecting_target, F.data.startswith("war:target:"))
async def declare_war_confirm(callback: CallbackQuery, state: FSMContext):
    target_house_id = int(callback.data.split(":")[2])
    data = await state.get_data()
    attacker_house_id = data["attacker_house_id"]

    async with AsyncSessionFactory() as session:
        war_repo = WarRepo(session)
        house_repo = HouseRepo(session)
        alliance_repo = AllianceRepo(session)
        chronicle_repo = ChronicleRepo(session)
        user_repo = UserRepo(session)

        attacker = await house_repo.get_by_id(attacker_house_id)
        defender = await house_repo.get_by_id(target_house_id)

        if not attacker or not defender:
            await callback.answer("❌ Xonadon topilmadi.", show_alert=True)
            await state.clear()
            return

        existing_alliance = await alliance_repo.get_active(attacker_house_id, target_house_id)
        if existing_alliance:
            await callback.answer("❌ Ittifoqchingizga urush e'lon qila olmaysiz!", show_alert=True)
            await state.clear()
            return

        grace_ends = datetime.utcnow() + timedelta(minutes=settings.GRACE_PERIOD_MINUTES)
        war = await war_repo.create_war(attacker_house_id, target_house_id, grace_ends)

        user = await user_repo.get_by_id(callback.from_user.id)
        if user and user.role == RoleEnum.HIGH_LORD:
            await alliance_repo.break_alliances_for_war(attacker_house_id)

        text = format_chronicle(
            "war_declared",
            attacker=attacker.name,
            defender=defender.name,
            region=defender.region.value,
        )
        bot = callback.bot
        tg_id = await post_to_chronicle(bot, text)
        await chronicle_repo.add("war_declared", text,
                                  house_id=attacker_house_id, tg_msg_id=tg_id)

        if defender.lord_id:
            try:
                await bot.send_message(
                    defender.lord_id,
                    f"⚔️ <b>URUSH E'LONI!</b>\n\n"
                    f"<b>{attacker.name}</b> sizga urush e'lon qildi!\n"
                    f"⏰ Grace Period: {settings.GRACE_PERIOD_MINUTES} daqiqa\n\n"
                    f"Qaror qiling: Taslim bo'lasizmi yoki jangga kirasizmi?",
                    reply_markup=surrender_or_fight_keyboard(war.id),
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"Mudofaachiga xabar yuborishda xato: {e}")

    await state.clear()
    await callback.answer()
    await callback.message.answer(
        f"⚔️ <b>Urush e'lon qilindi!</b>\n\n"
        f"🎯 Maqsad: {defender.name}\n"
        f"⏰ Grace Period: {settings.GRACE_PERIOD_MINUTES} daqiqa\n"
        f"Muddat: 23:00 gacha",
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("war:do_surrender:"))
async def do_surrender(callback: CallbackQuery):
    war_id = int(callback.data.split(":")[2])

    async with AsyncSessionFactory() as session:
        war_repo = WarRepo(session)
        house_repo = HouseRepo(session)
        user_repo = UserRepo(session)
        chronicle_repo = ChronicleRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)

        if not user or user.role not in [RoleEnum.LORD, RoleEnum.HIGH_LORD]:
            await callback.answer("❌ Faqat Lord qaror qabul qila oladi.", show_alert=True)
            return

        from sqlalchemy import select
        from database.models import War
        result = await session.execute(select(War).where(War.id == war_id))
        war = result.scalar_one_or_none()

        if not war or war.status not in [WarStatusEnum.GRACE_PERIOD, WarStatusEnum.FIGHTING]:
            await callback.answer("❌ Bu urush allaqachon tugagan.", show_alert=True)
            return

        if war.defender_house_id != user.house_id:
            await callback.answer("❌ Siz bu urushda mudofaachi emassiz.", show_alert=True)
            return

        defender = await house_repo.get_by_id(war.defender_house_id)
        attacker = await house_repo.get_by_id(war.attacker_house_id)

        loot = calculate_surrender_loot(
            defender.treasury,
            defender.total_soldiers,
            defender.total_dragons,
        )

        await house_repo.update_treasury(attacker.id, loot["gold"])
        await house_repo.update_treasury(defender.id, -loot["gold"])
        await session.execute(
            update(House).where(House.id == attacker.id).values(
                total_soldiers=House.total_soldiers + loot["soldiers"],
                total_dragons=House.total_dragons + loot["dragons"],
            )
        )
        await session.execute(
            update(House).where(House.id == defender.id).values(
                total_soldiers=House.total_soldiers - loot["soldiers"],
                total_dragons=House.total_dragons - loot["dragons"],
            )
        )

        await house_repo.set_occupation(defender.id, attacker.id, tax_rate=0.10)
        await war_repo.end_war(war_id, attacker.id, loot["gold"], surrendered=True)

        text = format_chronicle(
            "surrender",
            loser=defender.name,
            winner=attacker.name,
            loot=loot["gold"],
        )
        tg_id = await post_to_chronicle(callback.bot, text)
        await chronicle_repo.add("surrender", text, house_id=defender.id, tg_msg_id=tg_id)

        if attacker.lord_id:
            try:
                await callback.bot.send_message(
                    attacker.lord_id,
                    f"🏳️ <b>{defender.name} taslim bo'ldi!</b>\n"
                    f"💰 O'lja: {loot['gold']} oltin\n"
                    f"🗡️ +{loot['soldiers']} askar\n"
                    f"🐉 +{loot['dragons']} ajdar",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    await callback.answer()
    await callback.message.answer(
        f"🏳️ <b>Taslim bo'ldingiz.</b>\n\n"
        f"💰 Yo'qotildi: {loot['gold']} oltin\n"
        f"Doimiy soliq: 10% belgilandi.",
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("war:do_fight:"))
async def do_fight(callback: CallbackQuery):
    war_id = int(callback.data.split(":")[2])

    async with AsyncSessionFactory() as session:
        from sqlalchemy import select
        from database.models import War
        result = await session.execute(select(War).where(War.id == war_id))
        war = result.scalar_one_or_none()

        if not war:
            await callback.answer("❌ Urush topilmadi.", show_alert=True)
            return

        await callback.answer()
        await callback.message.answer(
            "⚔️ <b>Jangga kirishga qaror qildingiz!</b>\n\n"
            "Urush 23:00 gacha davom etadi va natijalar avtomatik hisoblanadi.\n"
            "Qo'shinlaringizni tayyorlang! 🗡️🐉",
            parse_mode="HTML"
        )


@router.callback_query(F.data == "war:surrender")
async def war_surrender_button(callback: CallbackQuery):
    """war_menu dagi '🏳️ Taslim Bo'lish' tugmasi"""
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        war_repo = WarRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)

        if not user or not user.house_id:
            await callback.answer("❌ Xonadoningiz yo'q.", show_alert=True)
            return

        if user.role not in [RoleEnum.LORD, RoleEnum.HIGH_LORD, RoleEnum.ADMIN]:
            await callback.answer("❌ Faqat Lord qaror qabul qila oladi.", show_alert=True)
            return

        active_war = await war_repo.get_active_war(user.house_id)
        if not active_war:
            await callback.answer("❌ Faol urush yo'q.", show_alert=True)
            return

        if active_war.defender_house_id != user.house_id:
            await callback.answer(
                "❌ Faqat mudofaachi taslim bo'la oladi.", show_alert=True
            )
            return

        await callback.answer()
        await callback.message.answer(
            "⚠️ <b>Taslim bo'lishni tasdiqlaysizmi?</b>\n\n"
            "Taslim bo'lsangiz resurslaringizning bir qismi yo'qoladi "
            "va 10% doimiy soliq belgilanadi.\n\n"
            "Tasdiqlash uchun quyidagi tugmani bosing:",
            reply_markup=surrender_or_fight_keyboard(active_war.id),
            parse_mode="HTML"
        )


@router.callback_query(F.data == "war:fight")
async def war_fight_button(callback: CallbackQuery):
    """war_menu dagi '🗡️ Jangga Kirish' tugmasi"""
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        war_repo = WarRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)

        if not user or not user.house_id:
            await callback.answer("❌ Xonadoningiz yo'q.", show_alert=True)
            return

        active_war = await war_repo.get_active_war(user.house_id)
        if not active_war:
            await callback.answer("❌ Faol urush yo'q.", show_alert=True)
            return

        if (
            active_war.defender_house_id == user.house_id
            and user.role in [RoleEnum.LORD, RoleEnum.HIGH_LORD, RoleEnum.ADMIN]
        ):
            await callback.answer()
            await callback.message.answer(
                "⚔️ <b>Jangga kirishni tasdiqlaysizmi?</b>\n\n"
                "Urush 23:00 gacha davom etadi va natijalar avtomatik hisoblanadi.\n"
                "Taslim bo'lish yoki jangda davom etish — qaror sizniki:",
                reply_markup=surrender_or_fight_keyboard(active_war.id),
                parse_mode="HTML"
            )
        else:
            await callback.answer()
            await callback.message.answer(
                "⚔️ <b>Jang davom etmoqda!</b>\n\n"
                "Urush 23:00 gacha davom etadi va natijalar avtomatik hisoblanadi.\n"
                "Qo'shinlaringizni tayyorlang! 🗡️🐉",
                parse_mode="HTML"
            )


@router.callback_query(F.data == "war:status")
async def war_status(callback: CallbackQuery):
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        war_repo = WarRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)

        if not user or not user.house_id:
            await callback.answer("❌ Xonadoningiz yo'q.", show_alert=True)
            return

        war = await war_repo.get_active_war(user.house_id)
        if not war:
            await callback.answer("✅ Hozirda faol urush yo'q.", show_alert=True)
            return

        is_attacker = war.attacker_house_id == user.house_id
        enemy = war.defender if is_attacker else war.attacker
        role_text = "Hujumchi ⚔️" if is_attacker else "Mudofaachi 🛡️"

        text = (
            f"📊 <b>URUSH HOLATI</b>\n\n"
            f"Sizning rolingiz: {role_text}\n"
            f"Raqib: <b>{enemy.name}</b>\n"
            f"Holat: {war.status.value}\n"
        )

        if war.grace_ends_at:
            remaining = war.grace_ends_at - datetime.utcnow()
            if remaining.total_seconds() > 0:
                mins = int(remaining.total_seconds() // 60)
                text += f"⏳ Grace Period: {mins} daqiqa qoldi\n"

        await callback.answer()
        await callback.message.answer(text, parse_mode="HTML")


@router.message(F.text.startswith("🗡️ Xiyonat"))
async def request_betrayal(message: Message, state: FSMContext):
    """A'zo urush paytida lordini tark etib, dushmandan panoh so'rashi"""
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        war_repo = WarRepo(session)
        house_repo = HouseRepo(session)
        chronicle_repo = ChronicleRepo(session)

        user = await user_repo.get_by_id(message.from_user.id)
        if not user or user.role != RoleEnum.MEMBER:
            await message.answer("❌ Faqat a'zolar xiyonat qila oladi.")
            return

        if not user.house_id:
            await message.answer("❌ Xonadoningiz yo'q.")
            return

        war = await war_repo.get_active_war(user.house_id)
        if not war or war.status not in [WarStatusEnum.GRACE_PERIOD, WarStatusEnum.FIGHTING]:
            await message.answer("❌ Hozirda faol urush yo'q. Xiyonat faqat urush paytida mumkin.")
            return

        enemy_house_id = (
            war.attacker_house_id
            if war.defender_house_id == user.house_id
            else war.defender_house_id
        )
        enemy_house = await house_repo.get_by_id(enemy_house_id)

        enemy_count = await user_repo.count_house_members(enemy_house_id)
        if enemy_count >= settings.MAX_HOUSE_MEMBERS:
            await message.answer("❌ Dushman xonadonida joy yo'q.")
            return

        old_house_id = user.house_id
        old_house = await house_repo.get_by_id(old_house_id)

        user.house_id = enemy_house_id
        user.region = enemy_house.region
        user.role = RoleEnum.MEMBER
        await session.commit()

        text = format_chronicle(
            "betrayal",
            user=user.full_name,
            refuge_house=enemy_house.name,
        )
        tg_id = await post_to_chronicle(message.bot, text)
        await chronicle_repo.add("betrayal", text, user_id=user.id, house_id=enemy_house_id, tg_msg_id=tg_id)

        if old_house and old_house.lord_id:
            try:
                await message.bot.send_message(
                    old_house.lord_id,
                    f"🗡️ <b>XIYONAT!</b>\n<b>{user.full_name}</b> jang paytida xonadonni tark etdi!",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        await message.answer(
            f"🗡️ Siz <b>{enemy_house.name}</b> xonadoniga o'tdingiz.\n"
            f"Xiyonat xronikaga yozildi.",
            parse_mode="HTML"
        )
