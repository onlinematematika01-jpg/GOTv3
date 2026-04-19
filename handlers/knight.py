"""
Ritsarlik mexanikasi
====================
Pog'onalar: Member < Knight < Lord < High Lord < Admin

Lord vakolatlari:
 - A'zoni ritsar saylash (max 10 ritsar)
 - Ritsarni xonadondan badarg'a qilish (askarlarini musodara qilib)
 - Ritsarga urush buyrug'i yuborish

Ritsar vakolatlari:
 - Bozordan faqat askar sotib olish (limit bor)
 - Kunlik farm olish (admin belgilagan miqdor)
 - Bank kreditidan foydalana olmaydi
 - Faqat o'z xonadoniga yordam bera oladi
 - Urush buyrug'ini tasdiqlash yoki rad etish
"""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from datetime import datetime, date

from database.engine import AsyncSessionFactory
from database.repositories import UserRepo, HouseRepo, WarRepo
from database.models import RoleEnum, WarStatusEnum, KnightOrderStatusEnum
from config.settings import settings
import logging

router = Router()
logger = logging.getLogger(__name__)

MAX_HOUSE_KNIGHTS = 10


def knight_order_keyboard(order_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Qabul qilaman", callback_data=f"knight_order:accept:{order_id}")
    builder.button(text="❌ Rad etaman",    callback_data=f"knight_order:reject:{order_id}")
    builder.adjust(2)
    return builder.as_markup()


def knight_select_keyboard(members, prefix="knight:appoint"):
    builder = InlineKeyboardBuilder()
    for m in members:
        builder.button(
            text=f"{m.full_name}",
            callback_data=f"{prefix}:{m.id}"
        )
    builder.adjust(1)
    return builder.as_markup()


def knight_manage_keyboard(knight_id: int, war_id: int = None):
    builder = InlineKeyboardBuilder()
    if war_id:
        builder.button(text="⚔️ Urushga buyruq yuborish", callback_data=f"knight:order:{knight_id}:{war_id}")
    builder.button(text="⚔️ Askarlarni musodara qilib badarg'a", callback_data=f"knight:exile_confiscate:{knight_id}")
    builder.button(text="🚪 Faqat badarg'a (askarlar qolsin)",   callback_data=f"knight:exile:{knight_id}")
    builder.adjust(1)
    return builder.as_markup()


# ─────────────────────────────────────────────
# LORD: RITSAR SAYLASH
# ─────────────────────────────────────────────

@router.message(F.text == "⚔️ Ritsar Saylash")
async def knight_appoint_menu(message: Message):
    async with AsyncSessionFactory() as session:
        user_repo   = UserRepo(session)
        house_repo  = HouseRepo(session)
        from database.repositories import KnightRepo
        knight_repo = KnightRepo(session)

        user = await user_repo.get_by_id(message.from_user.id)
        if not user or user.role not in [RoleEnum.LORD, RoleEnum.HIGH_LORD, RoleEnum.ADMIN]:
            await message.answer("❌ Faqat Lordlar ritsar saylay oladi.")
            return

        if not user.house_id:
            await message.answer("❌ Xonadoningiz yo'q.")
            return

        house = await house_repo.get_by_id(user.house_id)
        knight_count = await knight_repo.count_house_knights(user.house_id)

        # Xonadon a'zolari — faqat MEMBER rollidagilar
        members = [
            m for m in house.members
            if m.role == RoleEnum.MEMBER and m.id != user.id
        ]

        # Mavjud ritsarlar ro'yxati
        knights = await knight_repo.get_house_knights(user.house_id)
        knight_ids = {k.user_id for k in knights}

        knights_list = ""
        if knights:
            knight_users = [m for m in house.members if m.id in knight_ids]
            lines = []
            for k in knights:
                ku = next((m for m in house.members if m.id == k.user_id), None)
                name = ku.full_name if ku else f"ID:{k.user_id}"
                lines.append(f"⚔️ {name} — {k.soldiers} askar")
            knights_list = "\n<b>Hozirgi ritsarlar:</b>\n" + "\n".join(lines) + "\n\n"

        text = (
            f"⚔️ <b>RITSAR BOSHQARUVI</b>\n\n"
            f"{knights_list}"
            f"Ritsarlar: <b>{knight_count}/{MAX_HOUSE_KNIGHTS}</b>\n\n"
        )

        if knight_count >= MAX_HOUSE_KNIGHTS:
            await message.answer(
                text + "❌ Ritsarlar soni to'liq (10/10).",
                parse_mode="HTML"
            )
            return

        # Saylash mumkin bo'lgan a'zolar
        eligible = [m for m in members if m.id not in knight_ids and not m.is_exiled]

        if not eligible:
            await message.answer(
                text + "ℹ️ Ritsar saylash uchun xonadoningizda oddiy a'zo yo'q.",
                parse_mode="HTML"
            )
            return

        await message.answer(
            text + "👇 Qaysi a'zoni ritsar saylaysiz?",
            reply_markup=knight_select_keyboard(eligible),
            parse_mode="HTML"
        )


@router.callback_query(F.data.startswith("knight:appoint:"))
async def knight_appoint_confirm(callback: CallbackQuery):
    target_id = int(callback.data.split(":")[2])

    async with AsyncSessionFactory() as session:
        user_repo   = UserRepo(session)
        house_repo  = HouseRepo(session)
        from database.repositories import KnightRepo
        knight_repo = KnightRepo(session)

        lord = await user_repo.get_by_id(callback.from_user.id)
        if not lord or lord.role not in [RoleEnum.LORD, RoleEnum.HIGH_LORD, RoleEnum.ADMIN]:
            await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
            return

        target = await user_repo.get_by_id(target_id)
        if not target or target.house_id != lord.house_id:
            await callback.answer("❌ Bu a'zo xonadoningizda emas.", show_alert=True)
            return

        if target.role != RoleEnum.MEMBER:
            await callback.answer("❌ Faqat oddiy a'zoni ritsar saylash mumkin.", show_alert=True)
            return

        knight_count = await knight_repo.count_house_knights(lord.house_id)
        if knight_count >= MAX_HOUSE_KNIGHTS:
            await callback.answer("❌ Ritsarlar soni to'liq (10/10).", show_alert=True)
            return

        # Mavjud profil bormi?
        existing = await knight_repo.get_profile(target_id)
        if existing and existing.is_active:
            await callback.answer("❌ Bu a'zo allaqachon ritsar.", show_alert=True)
            return

        # Rolni o'zgartirish
        target.role = RoleEnum.KNIGHT

        # Profil yaratish yoki qayta faollashtirish
        if existing:
            existing.is_active = True
            existing.soldiers  = 0
            existing.house_id  = lord.house_id
        else:
            from database.models import KnightProfile
            profile = KnightProfile(
                user_id=target_id,
                house_id=lord.house_id,
                soldiers=0,
                is_active=True,
            )
            session.add(profile)

        await session.commit()

        await callback.answer()
        await callback.message.edit_text(
            f"⚔️ <b>{target.full_name}</b> endi <b>Ritsar</b>!\n\n"
            f"U bozordan askar sotib ola oladi va urushda sizga yordam beradi.",
            parse_mode="HTML"
        )

        # Ritsarga xabar
        try:
            house = await house_repo.get_by_id(lord.house_id)
            await callback.bot.send_message(
                target_id,
                f"⚔️ <b>SIZ RITSAR BO'LDINGIZ!</b>\n\n"
                f"<b>{lord.full_name}</b> sizni <b>{house.name}</b> xonadonining "
                f"Ritsari etib tayinladi!\n\n"
                f"Imkoniyatlaringiz:\n"
                f"• Bozordan askar sotib olish (limit: {settings.KNIGHT_SOLDIER_BUY_LIMIT} ta)\n"
                f"• Kunlik farm: {settings.KNIGHT_DAILY_FARM} askar\n"
                f"• Urushda xonadoningizga yordam berish",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Ritsarga xabar yuborishda xato: {e}")


# ─────────────────────────────────────────────
# LORD: RITSARNI BADARG'A QILISH
# ─────────────────────────────────────────────

@router.message(F.text == "⚔️ Ritsarlarni Boshqarish")
async def knight_manage_menu(message: Message):
    async with AsyncSessionFactory() as session:
        user_repo   = UserRepo(session)
        house_repo  = HouseRepo(session)
        from database.repositories import KnightRepo
        knight_repo = KnightRepo(session)

        user = await user_repo.get_by_id(message.from_user.id)
        if not user or user.role not in [RoleEnum.LORD, RoleEnum.HIGH_LORD, RoleEnum.ADMIN]:
            await message.answer("❌ Faqat Lordlar ritsarlarni boshqara oladi.")
            return

        knights = await knight_repo.get_house_knights(user.house_id)
        if not knights:
            await message.answer("ℹ️ Xonadoningizda ritsar yo'q.")
            return

        # Ritsarlar tugmalari
        builder = InlineKeyboardBuilder()
        for k in knights:
            ku = await user_repo.get_by_id(k.user_id)
            name = ku.full_name if ku else f"ID:{k.user_id}"
            builder.button(
                text=f"⚔️ {name} ({k.soldiers} askar)",
                callback_data=f"knight:manage:{k.user_id}"
            )
        builder.adjust(1)

        await message.answer(
            "⚔️ <b>RITSARLAR RO'YXATI</b>\n\nBoshqarmoqchi bo'lgan ritsarni tanlang:",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )


@router.callback_query(F.data.startswith("knight:manage:"))
async def knight_manage_detail(callback: CallbackQuery):
    knight_user_id = int(callback.data.split(":")[2])

    async with AsyncSessionFactory() as session:
        user_repo   = UserRepo(session)
        war_repo    = WarRepo(session)
        from database.repositories import KnightRepo
        knight_repo = KnightRepo(session)

        lord = await user_repo.get_by_id(callback.from_user.id)
        if not lord or lord.role not in [RoleEnum.LORD, RoleEnum.HIGH_LORD, RoleEnum.ADMIN]:
            await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
            return

        profile = await knight_repo.get_profile(knight_user_id)
        knight_user = await user_repo.get_by_id(knight_user_id)

        if not profile or not profile.is_active:
            await callback.answer("❌ Bu ritsar topilmadi.", show_alert=True)
            return

        # Faol urushlarni topish
        active_wars = await war_repo.get_active_wars(lord.house_id)

        builder = InlineKeyboardBuilder()
        if active_wars:
            for w in active_wars:
                from database.repositories import HouseRepo as HR
                house_repo = HR(session)
                enemy = w.defender if w.attacker_house_id == lord.house_id else w.attacker
                builder.button(
                    text=f"📨 Buyruq yuborish → {enemy.name}",
                    callback_data=f"knight:send_order:{knight_user_id}:{w.id}"
                )
        builder.button(
            text="💀 Musodara qilib badarg'a",
            callback_data=f"knight:exile_confiscate:{knight_user_id}"
        )
        builder.button(
            text="🚪 Faqat badarg'a (askarlar qolsin)",
            callback_data=f"knight:exile:{knight_user_id}"
        )
        builder.adjust(1)

        await callback.answer()
        await callback.message.edit_text(
            f"⚔️ <b>{knight_user.full_name}</b>\n"
            f"Askarlari: <b>{profile.soldiers}</b>\n\n"
            f"Amal tanlang:",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )


@router.callback_query(F.data.startswith("knight:exile_confiscate:"))
async def knight_exile_confiscate(callback: CallbackQuery):
    knight_user_id = int(callback.data.split(":")[2])

    async with AsyncSessionFactory() as session:
        user_repo   = UserRepo(session)
        house_repo  = HouseRepo(session)
        from database.repositories import KnightRepo
        knight_repo = KnightRepo(session)

        lord = await user_repo.get_by_id(callback.from_user.id)
        if not lord or lord.role not in [RoleEnum.LORD, RoleEnum.HIGH_LORD, RoleEnum.ADMIN]:
            await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
            return

        profile = await knight_repo.get_profile(knight_user_id)
        knight_user = await user_repo.get_by_id(knight_user_id)

        if not profile or not profile.is_active:
            await callback.answer("❌ Ritsar topilmadi.", show_alert=True)
            return

        confiscated = profile.soldiers

        # Askarlarni xonadon hisobiga o'tkazish
        house = await house_repo.get_by_id(lord.house_id)
        from sqlalchemy import update
        from database.models import House
        await session.execute(
            update(House).where(House.id == lord.house_id)
            .values(total_soldiers=House.total_soldiers + confiscated)
        )

        # Ritsarni deaktivlashtirish
        await knight_repo.deactivate(knight_user_id)
        knight_user.role = RoleEnum.MEMBER
        knight_user.is_exiled = True
        await session.commit()

        await callback.answer()
        await callback.message.edit_text(
            f"✅ <b>{knight_user.full_name}</b> badarg'a qilindi!\n"
            f"💀 Musodara qilingan askarlar: <b>{confiscated}</b>\n"
            f"Ular xonadon hisobiga o'tdi.",
            parse_mode="HTML"
        )

        try:
            await callback.bot.send_message(
                knight_user_id,
                f"❌ <b>BADARG'A!</b>\n\n"
                f"Lord <b>{lord.full_name}</b> sizni xonadondan badarg'a qildi!\n"
                f"Barcha askarlaringiz ({confiscated} ta) musodara qilindi.\n"
                f"Siz endi oddiy a'zo emassiz.",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Badarg'a xabari yuborishda xato: {e}")


@router.callback_query(F.data.startswith("knight:exile:"))
async def knight_exile_only(callback: CallbackQuery):
    knight_user_id = int(callback.data.split(":")[2])

    async with AsyncSessionFactory() as session:
        user_repo   = UserRepo(session)
        from database.repositories import KnightRepo
        knight_repo = KnightRepo(session)

        lord = await user_repo.get_by_id(callback.from_user.id)
        if not lord or lord.role not in [RoleEnum.LORD, RoleEnum.HIGH_LORD, RoleEnum.ADMIN]:
            await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
            return

        profile = await knight_repo.get_profile(knight_user_id)
        knight_user = await user_repo.get_by_id(knight_user_id)

        if not profile or not profile.is_active:
            await callback.answer("❌ Ritsar topilmadi.", show_alert=True)
            return

        await knight_repo.deactivate(knight_user_id)
        knight_user.role    = RoleEnum.MEMBER
        knight_user.is_exiled = True
        await session.commit()

        await callback.answer()
        await callback.message.edit_text(
            f"✅ <b>{knight_user.full_name}</b> badarg'a qilindi (askarlar saqlanmadi).",
            parse_mode="HTML"
        )

        try:
            await callback.bot.send_message(
                knight_user_id,
                f"❌ <b>BADARG'A!</b>\n\n"
                f"Lord <b>{lord.full_name}</b> sizni xonadondan chiqarib yubordi.",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Badarg'a xabari yuborishda xato: {e}")


# ─────────────────────────────────────────────
# LORD: RITSARGA URUSH BUYRUG'I YUBORISH
# ─────────────────────────────────────────────

class KnightOrderFSM(StatesGroup):
    entering_soldiers = State()


@router.callback_query(F.data.startswith("knight:send_order:"))
async def knight_send_order_start(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    knight_user_id = int(parts[2])
    war_id         = int(parts[3])

    async with AsyncSessionFactory() as session:
        user_repo   = UserRepo(session)
        from database.repositories import KnightRepo
        knight_repo = KnightRepo(session)

        lord = await user_repo.get_by_id(callback.from_user.id)
        if not lord or lord.role not in [RoleEnum.LORD, RoleEnum.HIGH_LORD, RoleEnum.ADMIN]:
            await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
            return

        profile = await knight_repo.get_profile(knight_user_id)
        knight_user = await user_repo.get_by_id(knight_user_id)

        if not profile or not profile.is_active:
            await callback.answer("❌ Ritsar topilmadi.", show_alert=True)
            return

        await state.update_data(
            knight_user_id=knight_user_id,
            war_id=war_id,
            max_soldiers=profile.soldiers,
            knight_name=knight_user.full_name
        )
        await state.set_state(KnightOrderFSM.entering_soldiers)

        await callback.answer()
        await callback.message.answer(
            f"📨 <b>{knight_user.full_name}</b> ga buyruq\n\n"
            f"Nechta askar bilan borishini belgilang?\n"
            f"Ritsarning mavjud askarlari: <b>{profile.soldiers}</b>\n"
            f"(0 kiritsangiz — barcha askarlari bilan boradi)",
            parse_mode="HTML"
        )


@router.message(KnightOrderFSM.entering_soldiers)
async def knight_send_order_soldiers(message: Message, state: FSMContext):
    data = await state.get_data()

    try:
        qty = int(message.text.strip())
        if qty < 0 or qty > data["max_soldiers"]:
            raise ValueError
    except (ValueError, TypeError):
        await message.answer(f"❌ 0 dan {data['max_soldiers']} gacha son kiriting.")
        return

    soldiers = qty if qty > 0 else data["max_soldiers"]

    async with AsyncSessionFactory() as session:
        user_repo   = UserRepo(session)
        from database.repositories import KnightRepo, KnightOrderRepo
        knight_repo = KnightRepo(session)
        order_repo  = KnightOrderRepo(session)

        lord = await user_repo.get_by_id(message.from_user.id)

        order = await order_repo.create(
            war_id=data["war_id"],
            house_id=lord.house_id,
            knight_id=data["knight_user_id"],
            lord_id=message.from_user.id,
            soldiers=soldiers
        )
        await session.commit()

        await state.clear()
        await message.answer(
            f"✅ Buyruq yuborildi!\n"
            f"Ritsar: <b>{data['knight_name']}</b>\n"
            f"Askarlar: <b>{soldiers}</b>",
            parse_mode="HTML"
        )

        # Ritsarga xabar
        try:
            await message.bot.send_message(
                data["knight_user_id"],
                f"📨 <b>URUSH BUYRUG'I!</b>\n\n"
                f"Lord <b>{lord.full_name}</b> sizni urushga chaqirmoqda!\n"
                f"Bilan borishingiz kerak: <b>{soldiers}</b> askar\n\n"
                f"Qabul qilasizmi?",
                reply_markup=knight_order_keyboard(order.id),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Ritsarga buyruq xabari yuborishda xato: {e}")


# ─────────────────────────────────────────────
# RITSAR: BUYRUQNI QABUL/RAD ETISH
# ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("knight_order:accept:"))
async def knight_order_accept(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[2])

    async with AsyncSessionFactory() as session:
        user_repo  = UserRepo(session)
        from database.repositories import KnightRepo, KnightOrderRepo, HouseRepo as HR
        knight_repo = KnightRepo(session)
        order_repo  = KnightOrderRepo(session)
        house_repo  = HR(session)

        user  = await user_repo.get_by_id(callback.from_user.id)
        order = await order_repo.get_by_id(order_id)

        if not order or order.knight_id != callback.from_user.id:
            await callback.answer("❌ Bu buyruq sizga tegishli emas.", show_alert=True)
            return

        if order.status != KnightOrderStatusEnum.PENDING:
            await callback.answer("ℹ️ Buyruqqa allaqachon javob bergansiz.", show_alert=True)
            return

        profile = await knight_repo.get_profile(callback.from_user.id)
        if not profile or profile.soldiers < order.soldiers:
            await callback.answer(
                f"❌ Yetarli askar yo'q! Sizda: {profile.soldiers if profile else 0}, "
                f"kerak: {order.soldiers}",
                show_alert=True
            )
            return

        # Askarlarni deployment ga qo'shish (WarDeployment orqali)
        from database.repositories import WarDeploymentRepo
        dep_repo = WarDeploymentRepo(session)
        existing = await dep_repo.get_deployment(order.war_id, order.house_id)

        if existing and not existing.is_auto_defend:
            await dep_repo.upsert(
                order.war_id, order.house_id,
                existing.soldiers + order.soldiers,
                existing.dragons,
                existing.scorpions
            )
        else:
            await dep_repo.upsert(order.war_id, order.house_id, order.soldiers, 0, 0)

        # Ritsarning askarlarini ayirish
        await knight_repo.remove_soldiers(callback.from_user.id, order.soldiers)
        await order_repo.set_status(order_id, KnightOrderStatusEnum.ACCEPTED)
        await session.commit()

        await callback.answer()
        await callback.message.edit_text(
            f"✅ <b>Buyruqni qabul qildingiz!</b>\n"
            f"{order.soldiers} askar urushga yuborildi.",
            parse_mode="HTML"
        )

        # Lordga xabar
        try:
            await callback.bot.send_message(
                order.lord_id,
                f"✅ <b>{user.full_name}</b> buyruqni qabul qildi!\n"
                f"{order.soldiers} askar jangga qo'shildi.",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Lordga xabar yuborishda xato: {e}")


@router.callback_query(F.data.startswith("knight_order:reject:"))
async def knight_order_reject(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[2])

    async with AsyncSessionFactory() as session:
        user_repo  = UserRepo(session)
        from database.repositories import KnightOrderRepo
        order_repo = KnightOrderRepo(session)

        user  = await user_repo.get_by_id(callback.from_user.id)
        order = await order_repo.get_by_id(order_id)

        if not order or order.knight_id != callback.from_user.id:
            await callback.answer("❌ Bu buyruq sizga tegishli emas.", show_alert=True)
            return

        if order.status != KnightOrderStatusEnum.PENDING:
            await callback.answer("ℹ️ Buyruqqa allaqachon javob bergansiz.", show_alert=True)
            return

        await order_repo.set_status(order_id, KnightOrderStatusEnum.REJECTED)
        await session.commit()

        await callback.answer()
        await callback.message.edit_text(
            "❌ <b>Buyruqni rad etdingiz.</b>\n\n"
            "Lord jazo chorasi ko'rishi mumkin!",
            parse_mode="HTML"
        )

        try:
            await callback.bot.send_message(
                order.lord_id,
                f"❌ <b>{user.full_name}</b> buyruqni RAD ETDI!\n\n"
                f"Jazo chorasi ko'ring:\n"
                f"• Askarlarini musodara qilib badarg'a\n"
                f"• Faqat badarg'a",
                reply_markup=InlineKeyboardBuilder()
                    .button(text="💀 Musodara + Badarg'a", callback_data=f"knight:exile_confiscate:{callback.from_user.id}")
                    .button(text="🚪 Faqat badarg'a",       callback_data=f"knight:exile:{callback.from_user.id}")
                    .adjust(1).as_markup(),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Lordga rad xabari yuborishda xato: {e}")


# ─────────────────────────────────────────────
# RITSAR: KUNLIK FARM
# ─────────────────────────────────────────────

@router.message(F.text == "🌾 Ritsar Farm")
async def knight_farm(message: Message):
    async with AsyncSessionFactory() as session:
        user_repo   = UserRepo(session)
        from database.repositories import KnightRepo
        knight_repo = KnightRepo(session)

        user = await user_repo.get_by_id(message.from_user.id)
        if not user or user.role != RoleEnum.KNIGHT:
            await message.answer("❌ Bu buyruq faqat ritsarlar uchun.")
            return

        profile = await knight_repo.get_profile(message.from_user.id)
        if not profile or not profile.is_active:
            await message.answer("❌ Ritsar profilingiz topilmadi.")
            return

        today = date.today()
        if profile.last_farm_date and profile.last_farm_date.date() >= today:
            await message.answer(
                f"⏳ Kunlik farmni allaqachon oldingiz!\n"
                f"Ertaga qayta kelishingiz mumkin."
            )
            return

        # Limitni tekshirish
        if profile.soldiers >= settings.KNIGHT_MAX_SOLDIERS:
            await message.answer(
                f"❌ Askar limiti to'liq! ({profile.soldiers}/{settings.KNIGHT_MAX_SOLDIERS})\n"
                f"Askarlaringizni urushda ishlating."
            )
            return

        amount = min(settings.KNIGHT_DAILY_FARM, settings.KNIGHT_MAX_SOLDIERS - profile.soldiers)
        await knight_repo.add_soldiers(message.from_user.id, amount)
        await knight_repo.update_farm_date(message.from_user.id, datetime.utcnow())
        await session.commit()

        await message.answer(
            f"🌾 <b>Farm olindi!</b>\n\n"
            f"+{amount} askar\n"
            f"Jami askar: <b>{profile.soldiers + amount}</b>/{settings.KNIGHT_MAX_SOLDIERS}",
            parse_mode="HTML"
        )


# ─────────────────────────────────────────────
# RITSAR: PROFIL
# ─────────────────────────────────────────────

@router.message(F.text == "⚔️ Ritsar Profili")
async def knight_profile(message: Message):
    async with AsyncSessionFactory() as session:
        user_repo   = UserRepo(session)
        from database.repositories import KnightRepo, KnightOrderRepo
        knight_repo = KnightRepo(session)
        order_repo  = KnightOrderRepo(session)

        user = await user_repo.get_by_id(message.from_user.id)
        if not user or user.role != RoleEnum.KNIGHT:
            await message.answer("❌ Bu buyruq faqat ritsarlar uchun.")
            return

        profile = await knight_repo.get_profile(message.from_user.id)
        if not profile:
            await message.answer("❌ Ritsar profilingiz topilmadi.")
            return

        pending_orders = await order_repo.get_pending_for_knight(message.from_user.id)

        today = date.today()
        farm_status = (
            "✅ Bugun olindi"
            if profile.last_farm_date and profile.last_farm_date.date() >= today
            else "🌾 Olishingiz mumkin"
        )

        text = (
            f"⚔️ <b>RITSAR PROFILI</b>\n\n"
            f"👤 {user.full_name}\n"
            f"🗡️ Askarlar: <b>{profile.soldiers}</b>/{settings.KNIGHT_MAX_SOLDIERS}\n"
            f"🌾 Kunlik farm: {farm_status} (+{settings.KNIGHT_DAILY_FARM})\n\n"
        )

        if pending_orders:
            text += f"📨 <b>Kutilayotgan buyruqlar: {len(pending_orders)}</b>\n"
            for o in pending_orders:
                text += f"  • {o.soldiers} askar bilan — {o.house.name} urushi\n"

        await message.answer(text, parse_mode="HTML")

        # Pending buyruqlarni ko'rsatish
        for o in pending_orders:
            await message.answer(
                f"📨 <b>Buyruq #{o.id}</b>\n"
                f"Urush: {o.house.name}\n"
                f"Askarlar: <b>{o.soldiers}</b>\n\n"
                f"Qabul qilasizmi?",
                reply_markup=knight_order_keyboard(o.id),
                parse_mode="HTML"
            )
