from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from datetime import datetime, timedelta
from database.engine import AsyncSessionFactory
from database.repositories import UserRepo, HouseRepo, WarRepo, AllianceGroupRepo, ChronicleRepo, WarDeploymentRepo, PrisonerRepo
from database.models import RoleEnum, WarStatusEnum, WarAllySupport
from keyboards import war_menu_keyboard, house_list_keyboard, surrender_or_fight_keyboard
from keyboards.keyboards import war_selection_keyboard, deploy_resources_keyboard, deploy_confirm_keyboard
from utils.battle import calculate_battle, calculate_surrender_loot
from utils.chronicle import post_to_chronicle, format_chronicle
from config.settings import settings
from sqlalchemy import update, select
from sqlalchemy.orm import selectinload
from database.models import User, House
import logging

router = Router()
logger = logging.getLogger(__name__)


class WarState(StatesGroup):
    selecting_target  = State()  # mavjud
    deploy_soldiers   = State()  # yangi — 3-bosqich
    deploy_dragons    = State()  # yangi
    deploy_scorpions  = State()  # yangi
    deploy_confirm    = State()  # yangi


async def get_war_sessions_from_db() -> list[dict]:
    """DB dan urush seanslarini oladi"""
    from database.repositories import BotSettingsRepo
    async with AsyncSessionFactory() as session:
        cfg = BotSettingsRepo(session)
        return await cfg.get_war_sessions()


async def is_war_time_async() -> bool:
    now = datetime.utcnow()
    local_hour = (now.hour + 5) % 24
    sessions = await get_war_sessions_from_db()
    return any(s["start"] <= local_hour < s["end"] for s in sessions)


def is_war_time() -> bool:
    now = datetime.utcnow()
    local_hour = (now.hour + 5) % 24
    return settings.WAR_START_HOUR <= local_hour < settings.WAR_END_HOUR


async def can_declare_war_async() -> bool:
    """Urush e'lon qilish mumkinmi — DB dan seanslarni tekshiradi"""
    now = datetime.utcnow()
    local_hour = (now.hour + 5) % 24
    local_minute = now.minute
    sessions = await get_war_sessions_from_db()
    for s in sessions:
        deadline = s.get("declare_deadline", s["end"] - 1)
        if local_hour < s["start"]:
            continue
        if local_hour > deadline:
            continue
        if local_hour == deadline and local_minute > 0:
            continue
        return True
    return False


def can_declare_war() -> bool:
    """
    Urush faqat 19:00–22:00 oralig'ida e'lon qilinishi mumkin.
    Sababki: 1 soatlik grace period kafolatlanishi kerak.
    """
    now = datetime.utcnow()
    local_hour = (now.hour + 5) % 24
    local_minute = now.minute
    if local_hour < settings.WAR_START_HOUR:
        return False
    if local_hour > settings.WAR_DECLARE_DEADLINE:
        return False
    if local_hour == settings.WAR_DECLARE_DEADLINE and local_minute > 0:
        return False
    return True


async def get_war_declare_error_message_async() -> str:
    """E'lon qilib bo'lmaydigan vaqtda aniq xato xabari (DB dan seanslarni o'qiydi)"""
    now = datetime.utcnow()
    local_hour = (now.hour + 5) % 24
    sessions = await get_war_sessions_from_db()

    # Eng yaqin kelayotgan seansni topish
    if sessions:
        starts = sorted(s["start"] for s in sessions)
        deadlines = sorted(s.get("declare_deadline", s["end"] - 1) for s in sessions)
        ends = sorted(s["end"] for s in sessions)

        # Hozirgi vaqt biror seans ichidami?
        for s in sessions:
            deadline = s.get("declare_deadline", s["end"] - 1)
            if s["start"] <= local_hour < s["end"]:
                # Seans ichida, lekin deadline o'tgan
                return (
                    f"❌ Urush e'lon qilish muddati o'tdi!\n\n"
                    f"🕙 Qat'iy qoida: urush faqat <b>{deadline:02d}:00 gacha</b> e'lon qilinishi mumkin.\n"
                    f"📌 Sabab: mudofaachiga kamida 1 soat (grace period) kafolatlanishi shart.\n\n"
                    f"⏰ Hozir: {local_hour:02d}:{now.minute:02d}\n"
                    f"📅 Keyingi seans boshlanishini kuting."
                )

        # Hech qaysi seans ichida emas — eng yaqin seans boshlanishini ko'rsat
        next_start = min((s["start"] for s in sessions if s["start"] > local_hour), default=starts[0])
        return (
            f"❌ Urush e'lon qilish vaqti emas!\n"
            f"📅 Urush seanslari: {', '.join(str(s['start']) + ':00–' + str(s['end']) + ':00' for s in sessions)}\n"
            f"⏰ Hozir: {local_hour:02d}:{now.minute:02d}"
        )

    # DB da seans yo'q — fallback
    return (
        f"❌ Urush vaqti emas!\n"
        f"⏰ Hozir: {local_hour:02d}:{now.minute:02d}"
    )


def get_war_declare_error_message() -> str:
    """E'lon qilib bo'lmaydigan vaqtda aniq xato xabari (settings fallback)"""
    now = datetime.utcnow()
    local_hour = (now.hour + 5) % 24
    if local_hour < settings.WAR_START_HOUR:
        return (
            f"❌ Urush e'lon qilish vaqti emas!\n"
            f"📅 Urush vaqti: 19:00 – 22:00\n"
            f"⏰ Hozir: {local_hour:02d}:{now.minute:02d}"
        )
    else:
        return (
            f"❌ Urush e'lon qilish muddati o'tdi!\n\n"
            f"🕙 Qat'iy qoida: urush faqat <b>22:00 gacha</b> e'lon qilinishi mumkin.\n"
            f"📌 Sabab: mudofaachiga kamida 1 soat (grace period) kafolatlanishi shart.\n\n"
            f"⏰ Hozir: {local_hour:02d}:{now.minute:02d}\n"
            f"📅 Ertaga 19:00 dan boshlab e'lon qilishingiz mumkin."
        )


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
        active_wars = []
        if user.house_id:
            active_wars = await war_repo.get_active_wars(user.house_id)

        war_time_ok = await is_war_time_async()
        war_time_text = "✅ Urush vaqti" if war_time_ok else "❌ Urush vaqti emas"

        # DB dan seanslarni olib, ko'rsatish uchun formatlash
        sessions = await get_war_sessions_from_db()
        if sessions:
            sessions_text = ", ".join(f"{s['start']:02d}:00–{s['end']:02d}:00" for s in sessions)
        else:
            sessions_text = f"{settings.WAR_START_HOUR:02d}:00–{settings.WAR_END_HOUR:02d}:00"

        text = (
            "⚔️ <b>URUSH MARKAZI</b>\n\n"
            f"🕰️ {war_time_text}\n"
            f"📅 Urush seanslari: {sessions_text}\n\n"
        )

        if active_wars:
            text += f"🔥 <b>Faol urushlar ({len(active_wars)}):</b>\n"
            for aw in active_wars:
                other = aw.defender if aw.attacker_house_id == user.house_id else aw.attacker
                role_emoji = "⚔️" if aw.attacker_house_id == user.house_id else "🛡️"
                text += f"{role_emoji} <b>{other.name}</b> — {aw.status.value}\n"
                if aw.grace_ends_at:
                    remaining = aw.grace_ends_at - datetime.utcnow()
                    if remaining.total_seconds() > 0:
                        mins = int(remaining.total_seconds() // 60)
                        text += f"   ⏳ Grace: {mins} daqiqa qoldi\n"

        await message.answer(
            text,
            reply_markup=war_menu_keyboard(is_lord, bool(active_wars)),
            parse_mode="HTML"
        )


@router.callback_query(F.data == "war:declare")
async def declare_war_start(callback: CallbackQuery, state: FSMContext):
    if not await can_declare_war_async():
        error_msg = await get_war_declare_error_message_async()
        await callback.answer(error_msg, show_alert=True)
        return

    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        war_repo = WarRepo(session)
        house_repo = HouseRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)

        if not user or user.role not in [RoleEnum.LORD, RoleEnum.HIGH_LORD]:
            await callback.answer("❌ Faqat Lordlar urush e'lon qila oladi.", show_alert=True)
            return

        if not user.house_id:
            await callback.answer("❌ Xonadoningiz yo'q.", show_alert=True)
            return

        attacker_house = await house_repo.get_by_id(user.house_id)
        if not attacker_house:
            await callback.answer("❌ Xonadoningiz topilmadi.", show_alert=True)
            return

        # Resurs tekshiruvi — kamida bitta resurs bo'lsin
        if (attacker_house.total_soldiers == 0 and
                attacker_house.total_dragons == 0 and
                attacker_house.total_scorpions == 0):
            await callback.answer("❌ Urush ochish uchun resurslaringiz yo'q.", show_alert=True)
            return

        # 7-BOSQICH: Asir lord urush ocha olmaydi
        prisoner_repo = PrisonerRepo(session)
        is_prisoner = await prisoner_repo.get_by_prisoner_user(user.id)
        if is_prisoner:
            await callback.answer("❌ Asirlikda urush e'lon qilib bo'lmaydi!", show_alert=True)
            return

        # High Lord — barcha hududlarga urush ochishi mumkin
        # Lord — faqat o'z hududidagi xonadonga urush ochishi mumkin
        # ISTISNO: Agar maqsad xonadon o'ldirilgan lord xonadoni bo'lsa —
        #           executed_lord_flag=True → hudud cheklovi yo'q
        if user.role == RoleEnum.HIGH_LORD:
            all_houses = await house_repo.get_all()
            targets = [h for h in all_houses if h.id != user.house_id]
            hudud_text = "🌍 Barcha hududlar"
        else:
            # executed_lord_flag=True bo'lgan xonadonlarni topish
            from sqlalchemy import select as _sel
            from database.models import War as _War
            executed_wars = await session.execute(
                _sel(_War.defender_house_id)
                .where(_War.executed_lord_flag == True)
                .distinct()
            )
            executed_house_ids = {row[0] for row in executed_wars.fetchall()}

            all_houses = await house_repo.get_all()
            targets = [
                h for h in all_houses
                if h.id != user.house_id and (
                    h.region == attacker_house.region or
                    h.id in executed_house_ids
                )
            ]
            if executed_house_ids & {h.id for h in targets if h.region != attacker_house.region}:
                hudud_text = (
                    f"📍 Hudud: <b>{attacker_house.region.value}</b>\n"
                    f"⚠️ O'ldirilgan lord xonadonlariga ham urush ochish mumkin"
                )
            else:
                hudud_text = f"📍 Hudud: <b>{attacker_house.region.value}</b>"

        if not targets:
            await callback.answer(
                "❌ Hujum qilish uchun boshqa xonadon yo'q." if user.role == RoleEnum.HIGH_LORD
                else f"❌ {attacker_house.region.value} hududida hujum qilish uchun boshqa xonadon yo'q.",
                show_alert=True
            )
            return

        await state.set_state(WarState.selecting_target)
        await state.update_data(attacker_house_id=user.house_id)

        await callback.answer()
        await callback.message.answer(
            f"🎯 <b>Hujum maqsadini tanlang:</b>\n"
            f"{hudud_text}",
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
        group_repo = AllianceGroupRepo(session)
        chronicle_repo = ChronicleRepo(session)
        user_repo = UserRepo(session)

        attacker = await house_repo.get_by_id(attacker_house_id)
        defender = await house_repo.get_by_id(target_house_id)

        if not attacker or not defender:
            await callback.answer("❌ Xonadon topilmadi.", show_alert=True)
            await state.clear()
            return

        # Guruh a'zosiga urush e'lon qilib bo'lmaydi
        group_repo = AllianceGroupRepo(session)
        attacker_group = await group_repo.get_house_active_group(attacker_house_id)
        defender_group = await group_repo.get_house_active_group(target_house_id)
        if (
            attacker_group and defender_group
            and attacker_group.id == defender_group.id
        ):
            await callback.answer(
                f"❌ «{attacker_group.name}» ittifoq guruhingiz a'zosiga urush e'lon qilib bo'lmaydi!",
                show_alert=True
            )
            await state.clear()
            return

        # BOSQICH 9 — Vassal hukmdorga urush ochmoqchi bo'lsa garnizon tekshiriladi
        if (
            attacker.is_under_occupation
            and attacker.occupier_house_id == defender.id
        ):
            from database.repositories import TerritoryGarrisonRepo
            garrison_repo = TerritoryGarrisonRepo(session)
            attacker_user = await user_repo.get_by_id(callback.from_user.id)
            if attacker_user and attacker_user.region:
                garrison = await garrison_repo.get_by_region(attacker_user.region)
                if garrison and garrison.soldiers > 0:
                    all_vassals = await house_repo.get_vassals_by_hukmdor(defender.id)
                    total_vassal_soldiers = sum(h.total_soldiers for h in all_vassals)
                    if garrison.soldiers >= total_vassal_soldiers // 2:
                        await callback.answer(
                            f"⛓️ Hukmdorga qarshi urush ocholmaysiz!\n"
                            f"Hudud garnizoni ({garrison.soldiers} askar) barcha vassallarning "
                            f"qo'shini yarmidan ko'p.\n"
                            f"Isyon mexanikasidan foydalaning.",
                            show_alert=True
                        )
                        await state.clear()
                        return

        grace_ends = datetime.utcnow() + timedelta(minutes=settings.GRACE_PERIOD_MINUTES)

        # Xavfsizlik: grace period har qanday holatda 23:00 (mahalliy) dan oshmasin
        # UTC = mahalliy - 5 soat, ya'ni 23:00 mahalliy = 18:00 UTC
        now = datetime.utcnow()
        war_end_today_utc = now.replace(hour=18, minute=0, second=0, microsecond=0)
        if war_end_today_utc <= now:
            # 23:00 mahalliy allaqachon o'tgan — ertangi kunga o'tkazish mumkin emas,
            # lekin can_declare_war() allaqachon buni bloklagan. Shu sababli bu yerga kelmasligimiz kerak.
            await callback.answer("❌ Texnik xato: urush vaqti o'tib ketgan.", show_alert=True)
            await state.clear()
            return
        if grace_ends > war_end_today_utc:
            grace_ends = war_end_today_utc

        war = await war_repo.create_war(attacker_house_id, target_house_id, grace_ends)

        user = await user_repo.get_by_id(callback.from_user.id)

        # 2-QOIDA: yangi urush ochilganda — defender (target_house) boshqa urushda
        # ittifoqchi sifatida ishtirok etayotgan bo'lsa, o'sha yordam bekor qilinadi
        # va yordamni olgan tomon xabardor qilinadi
        cancelled_supports = await session.execute(
            select(WarAllySupport)
            .where(WarAllySupport.ally_house_id == target_house_id)
            .options(selectinload(WarAllySupport.war), selectinload(WarAllySupport.ally_house))
        )
        cancelled_list = cancelled_supports.scalars().all()
        for sup in cancelled_list:
            # Faqat hali faol urushlar uchun
            if sup.war and sup.war.status in [WarStatusEnum.GRACE_PERIOD, WarStatusEnum.FIGHTING]:
                # Beneficiary (yordamni olgan tomon) ni topish
                beneficiary_house_id = (
                    sup.war.attacker_house_id if sup.side == "attacker"
                    else sup.war.defender_house_id
                )
                beneficiary = await house_repo.get_by_id(beneficiary_house_id)

                # Yordamni o'chirish
                await session.delete(sup)

                # Beneficiaryga xabar
                if beneficiary and beneficiary.lord_id:
                    try:
                        await callback.bot.send_message(
                            beneficiary.lord_id,
                            f"⚠️ <b>ITTIFOQCHI YORDAMI BEKOR QILINDI!</b>\n\n"
                            f"<b>{defender.name}</b> xonadoniga urush e'lon qilindi!\n"
                            f"Ular sizga bergan yordamlari avtomatik bekor bo'ldi.",
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logger.warning(f"Beneficiaryga xabar yuborishda xato: {e}")

        await session.commit()

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

        # Kuchlar nisbatini ham kanalga yuborish
        from utils.chronicle import post_war_power_update
        try:
            await post_war_power_update(bot, war.id)
        except Exception as e:
            logger.warning(f"Kuchlar nisbati xabarida xato: {e}")

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

        # Ikkala lordga ham resurs yuborish tugmasi
        deploy_kb = deploy_resources_keyboard(war.id)
        if attacker.lord_id:
            try:
                await bot.send_message(
                    attacker.lord_id,
                    f"🗡️ <b>Resurslaringizni jangga yuboring!</b>\n\n"
                    f"⏰ Grace period: {settings.GRACE_PERIOD_MINUTES} daqiqa\n"
                    f"Resurs yubormagan tomon barcha resursi bilan avtomatik mudofaaga o'tadi.",
                    reply_markup=deploy_kb,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"Hujumchiga deploy xabari yuborishda xato: {e}")
        if defender.lord_id:
            try:
                await bot.send_message(
                    defender.lord_id,
                    f"🛡️ <b>Mudofaa resurslaringizni yuboring!</b>\n\n"
                    f"⏰ Grace period: {settings.GRACE_PERIOD_MINUTES} daqiqa\n"
                    f"Resurs yubormagan tomon barcha resursi bilan avtomatik mudofaaga o'tadi.",
                    reply_markup=deploy_resources_keyboard(war.id),
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"Mudofaachiga deploy xabari yuborishda xato: {e}")

    # Ikkala tomon ittifoqchilariga xabar — session yopilgandan keyin
    from handlers.war_ally import notify_allies
    try:
        await notify_allies(bot, war, attacker, "attacker")
    except Exception as e:
        logger.warning(f"Hujumchi ittifoqchilariga xabar yuborishda xato: {e}")
    try:
        await notify_allies(bot, war, defender, "defender")
    except Exception as e:
        logger.warning(f"Mudofaachi ittifoqchilariga xabar yuborishda xato: {e}")

    await state.clear()
    await callback.answer()
    # DB dan urush tugash vaqtini olish
    _sessions = await get_war_sessions_from_db()
    _war_ends = " / ".join(f"{s['end']:02d}:00" for s in _sessions) if _sessions else f"{settings.WAR_END_HOUR:02d}:00"

    await callback.message.answer(
        f"⚔️ <b>Urush e'lon qilindi!</b>\n\n"
        f"🎯 Maqsad: {defender.name}\n"
        f"⏰ Grace Period: {settings.GRACE_PERIOD_MINUTES} daqiqa\n"
        f"Muddat: {_war_ends} gacha",
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

        # Custom itemlar o'ljasi — taslim bo'lishda ham 51% o'tkaziladi
        from database.repositories import CustomItemRepo
        import math
        from config.settings import settings as _settings
        custom_repo = CustomItemRepo(session)
        defender_items = await custom_repo.get_house_items_with_info(defender.id)
        item_loot_parts = []
        for row in defender_items:
            loot_qty = math.ceil(row.quantity * _settings.WAR_LOOT_PERCENT)
            if loot_qty > 0:
                row.quantity = max(0, row.quantity - loot_qty)
                await custom_repo.add_house_item(attacker.id, row.item_id, loot_qty)
                item_loot_parts.append(f"{row.item.emoji}{row.item.name}×{loot_qty}")
        await session.commit()

        # Agar attacker avval defender vassali bo'lgan bo'lsa — ozod bo'ladi
        if attacker.is_under_occupation and attacker.occupier_house_id == defender.id:
            await house_repo.clear_occupation(attacker.id)
        await house_repo.set_occupation(defender.id, attacker.id, tax_rate=0.10)

        # Agar defender HIGH_LORD bo'lgan bo'lsa — unvonini attacker ga o'tkazish
        if defender.high_lord_id and attacker.region == defender.region:
            from sqlalchemy import update as sa_update
            from database.models import User as UserModel, RoleEnum as RE

            # Defender HIGH_LORD unvonini yo'qotadi
            defender.high_lord_id = None
            await session.execute(
                sa_update(UserModel)
                .where(UserModel.id == defender.lord_id, UserModel.role == RE.HIGH_LORD)
                .values(role=RE.LORD)
            )
            if defender.lord_id:
                try:
                    await callback.bot.send_message(
                        defender.lord_id,
                        f"👑 <b>HUKMDORLIK YO'QOLDI!</b>\n\n"
                        f"Taslim bo'lganingiz sababli <b>{defender.region.value}</b> "
                        f"hududidagi Hukmdorlik unvoningizni yo'qotdingiz.",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

            # Attacker HIGH_LORD bo'ladi
            from database.models import House as HouseModel
            from sqlalchemy import select as sa_select
            attacker_fresh = (await session.execute(
                sa_select(HouseModel).where(HouseModel.id == attacker.id)
            )).scalar_one_or_none()
            if attacker_fresh and attacker_fresh.lord_id:
                attacker_fresh.high_lord_id = attacker_fresh.lord_id
                await session.execute(
                    sa_update(UserModel)
                    .where(UserModel.id == attacker_fresh.lord_id)
                    .values(role=RE.HIGH_LORD)
                )
                try:
                    await callback.bot.send_message(
                        attacker_fresh.lord_id,
                        f"👑 <b>SIZ HUKMDOR BO'LDINGIZ!</b>\n\n"
                        f"<b>{defender.region.value}</b> hududining "
                        f"<b>HUKMDORI</b> bo'ldingiz!\n"
                        f"Barcha vassal xonadonlar sizga o'lpon to'laydi.",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

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
                    f"🐉 +{loot['dragons']} ajdar"
                    + (f"\n🎁 Itemlar: {', '.join(item_loot_parts)}" if item_loot_parts else ""),
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

        # DB dan urush tugash vaqtini olish
        sessions = await get_war_sessions_from_db()
        if sessions:
            war_ends_text = " / ".join(f"{s['end']:02d}:00" for s in sessions)
        else:
            war_ends_text = f"{settings.WAR_END_HOUR:02d}:00"

        await callback.answer()
        await callback.message.answer(
            "⚔️ <b>Jangga kirishga qaror qildingiz!</b>\n\n"
            f"Urush {war_ends_text} gacha davom etadi va natijalar avtomatik hisoblanadi.\n"
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

        active_wars = await war_repo.get_active_wars(user.house_id)
        # Faqat mudofaachi sifatidagi urushlarni filtrlash
        defender_wars = [w for w in active_wars if w.defender_house_id == user.house_id]

        if not defender_wars:
            await callback.answer("❌ Taslim bo'lish uchun faol urush yo'q.", show_alert=True)
            return

        if len(defender_wars) == 1:
            active_war = defender_wars[0]
            await callback.answer()
            await callback.message.answer(
                "⚠️ <b>Taslim bo'lishni tasdiqlaysizmi?</b>\n\n"
                "Taslim bo'lsangiz resurslaringizning bir qismi yo'qoladi "
                "va 10% doimiy soliq belgilanadi.\n\n"
                "Tasdiqlash uchun quyidagi tugmani bosing:",
                reply_markup=surrender_or_fight_keyboard(active_war.id),
                parse_mode="HTML"
            )
        else:
            # Bir nechta urush — tanlash
            await callback.answer()
            await callback.message.answer(
                "⚠️ Qaysi urushda taslim bo'lmoqchisiz?",
                reply_markup=war_selection_keyboard(defender_wars, "do_surrender", user.house_id),
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

        active_wars = await war_repo.get_active_wars(user.house_id)
        if not active_wars:
            await callback.answer("❌ Faol urush yo'q.", show_alert=True)
            return

        _sessions = await get_war_sessions_from_db()
        _war_ends = " / ".join(f"{s['end']:02d}:00" for s in _sessions) if _sessions else f"{settings.WAR_END_HOUR:02d}:00"

        if len(active_wars) == 1:
            active_war = active_wars[0]
            if (
                active_war.defender_house_id == user.house_id
                and user.role in [RoleEnum.LORD, RoleEnum.HIGH_LORD, RoleEnum.ADMIN]
            ):
                await callback.answer()
                await callback.message.answer(
                    "⚔️ <b>Jangga kirishni tasdiqlaysizmi?</b>\n\n"
                    f"Urush {_war_ends} gacha davom etadi va natijalar avtomatik hisoblanadi.\n"
                    "Taslim bo'lish yoki jangda davom etish — qaror sizniki:",
                    reply_markup=surrender_or_fight_keyboard(active_war.id),
                    parse_mode="HTML"
                )
            else:
                await callback.answer()
                await callback.message.answer(
                    "⚔️ <b>Jang davom etmoqda!</b>\n\n"
                    f"Urush {_war_ends} gacha davom etadi va natijalar avtomatik hisoblanadi.\n"
                    "Qo'shinlaringizni tayyorlang! 🗡️🐉",
                    parse_mode="HTML"
                )
        else:
            # Bir nechta urush — tanlash
            await callback.answer()
            await callback.message.answer(
                "⚔️ Qaysi urush holatini ko'rmoqchisiz?",
                reply_markup=war_selection_keyboard(active_wars, "do_fight", user.house_id),
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

        wars = await war_repo.get_active_wars(user.house_id)
        if not wars:
            await callback.answer("✅ Hozirda faol urush yo'q.", show_alert=True)
            return

        text = "📊 <b>URUSH HOLATI</b>\n\n"
        for war in wars:
            is_attacker = war.attacker_house_id == user.house_id
            enemy = war.defender if is_attacker else war.attacker
            role_text = "Hujumchi ⚔️" if is_attacker else "Mudofaachi 🛡️"
            text += (
                f"{role_text} — <b>{enemy.name}</b>\n"
                f"Holat: {war.status.value}\n"
            )
            if war.grace_ends_at:
                remaining = war.grace_ends_at - datetime.utcnow()
                if remaining.total_seconds() > 0:
                    mins = int(remaining.total_seconds() // 60)
                    text += f"⏳ Grace Period: {mins} daqiqa qoldi\n"
            text += "\n"

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

        wars = await war_repo.get_active_wars(user.house_id)
        war = next((w for w in wars if w.status in [WarStatusEnum.GRACE_PERIOD, WarStatusEnum.FIGHTING]), None)
        if not war:
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


# ─────────────────────────────────────────────────────────────────
# 3-BOSQICH: RESURS YUBORISH (DEPLOYMENT) FSM HANDLERLARI
# ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("deploy:start:"))
async def deploy_start(callback: CallbackQuery, state: FSMContext):
    """Resurs yuborish FSM ni boshlash"""
    war_id = int(callback.data.split(":")[2])

    async with AsyncSessionFactory() as session:
        user_repo  = UserRepo(session)
        house_repo = HouseRepo(session)
        dep_repo   = WarDeploymentRepo(session)
        war_repo   = WarRepo(session)

        user = await user_repo.get_by_id(callback.from_user.id)
        if not user or user.role not in [RoleEnum.LORD, RoleEnum.HIGH_LORD]:
            await callback.answer("❌ Faqat lord resurs yuboradi.", show_alert=True)
            return

        if not user.house_id:
            await callback.answer("❌ Xonadoningiz yo'q.", show_alert=True)
            return

        # Urush hali faolmi?
        war = await war_repo.get_by_id(war_id)
        if not war or war.status not in [WarStatusEnum.DECLARED, WarStatusEnum.GRACE_PERIOD]:
            await callback.answer("❌ Resurs yuborish muddati o'tdi yoki urush topilmadi.", show_alert=True)
            return

        # Faqat urush ishtirokchisi yuborishi mumkin
        if user.house_id not in [war.attacker_house_id, war.defender_house_id]:
            await callback.answer("❌ Siz bu urush ishtirokchisi emassiz.", show_alert=True)
            return

        house = await house_repo.get_by_id(user.house_id)

        # Allaqachon deployment bor bo'lsa — ustiga qo'shish mumkinligini bildirish
        existing = await dep_repo.get_deployment(war_id, user.house_id)
        extra_text = ""
        if existing and not existing.is_auto_defend:
            extra_text = (
                f"\n\n📦 <b>Oldingi yuborish:</b>\n"
                f"🗡️ {existing.soldiers} askar | "
                f"🐉 {existing.dragons} ajdar | "
                f"🏹 {existing.scorpions} skorpion\n"
                f"<i>Yangi miqdor ustiga qo'shiladi.</i>"
            )

        await state.update_data(
            war_id=war_id,
            max_soldiers=house.total_soldiers,
            max_dragons=house.total_dragons,
            max_scorpions=house.total_scorpions,
            dep_soldiers=0,
            dep_dragons=0,
            dep_scorpions=0,
        )
        await state.set_state(WarState.deploy_soldiers)
        await callback.answer()
        await callback.message.answer(
            f"🗡️ <b>Nechta askar yuborasiz?</b>\n"
            f"Mavjud: <b>{house.total_soldiers}</b> askar\n"
            f"(0 kiriting — askar yubormaslik){extra_text}",
            parse_mode="HTML"
        )


@router.message(WarState.deploy_soldiers)
async def deploy_soldiers_input(message: Message, state: FSMContext):
    data = await state.get_data()
    try:
        qty = int(message.text.strip())
        if qty < 0 or qty > data["max_soldiers"]:
            raise ValueError
    except (ValueError, TypeError):
        await message.answer(
            f"❌ 0 dan {data['max_soldiers']} gacha butun son kiriting."
        )
        return

    await state.update_data(dep_soldiers=qty)
    await state.set_state(WarState.deploy_dragons)
    await message.answer(
        f"🐉 <b>Nechta ajdar yuborasiz?</b>\n"
        f"Mavjud: <b>{data['max_dragons']}</b> ajdar\n"
        f"(0 kiriting — ajdar yubormaslik)",
        parse_mode="HTML"
    )


@router.message(WarState.deploy_dragons)
async def deploy_dragons_input(message: Message, state: FSMContext):
    data = await state.get_data()
    try:
        qty = int(message.text.strip())
        if qty < 0 or qty > data["max_dragons"]:
            raise ValueError
    except (ValueError, TypeError):
        await message.answer(
            f"❌ 0 dan {data['max_dragons']} gacha butun son kiriting."
        )
        return

    await state.update_data(dep_dragons=qty)
    await state.set_state(WarState.deploy_scorpions)
    await message.answer(
        f"🏹 <b>Nechta skorpion yuborasiz?</b>\n"
        f"Mavjud: <b>{data['max_scorpions']}</b> skorpion\n"
        f"(0 kiriting — skorpion yubormaslik)",
        parse_mode="HTML"
    )


@router.message(WarState.deploy_scorpions)
async def deploy_scorpions_input(message: Message, state: FSMContext):
    data = await state.get_data()
    try:
        qty = int(message.text.strip())
        if qty < 0 or qty > data["max_scorpions"]:
            raise ValueError
    except (ValueError, TypeError):
        await message.answer(
            f"❌ 0 dan {data['max_scorpions']} gacha butun son kiriting."
        )
        return

    await state.update_data(dep_scorpions=qty)
    data = await state.get_data()
    await state.set_state(WarState.deploy_confirm)

    total = data["dep_soldiers"] + data["dep_dragons"] + data["dep_scorpions"]
    if total == 0:
        warn = "\n\n⚠️ <i>Barcha 0 — resurs yubormaysiz. Tasdiqlasangiz, mavjud barcha resurs bilan avtomatik mudofaaga o'tasiz.</i>"
    else:
        warn = "\n\n⚠️ Tasdiqlangach resurslar darhol xonadon hisobidan ayiriladi!"

    await message.answer(
        f"📋 <b>Tasdiqlash:</b>\n\n"
        f"🗡️ Askar: {data['dep_soldiers']}\n"
        f"🐉 Ajdar: {data['dep_dragons']}\n"
        f"🏹 Skorpion: {data['dep_scorpions']}"
        f"{warn}",
        reply_markup=deploy_confirm_keyboard(data["war_id"]),
        parse_mode="HTML"
    )


@router.callback_query(WarState.deploy_confirm, F.data.startswith("deploy:confirm:"))
async def deploy_confirm_handler(callback: CallbackQuery, state: FSMContext):
    data      = await state.get_data()
    war_id    = data["war_id"]
    soldiers  = data["dep_soldiers"]
    dragons   = data["dep_dragons"]
    scorpions = data["dep_scorpions"]

    async with AsyncSessionFactory() as session:
        user_repo  = UserRepo(session)
        house_repo = HouseRepo(session)
        dep_repo   = WarDeploymentRepo(session)
        war_repo   = WarRepo(session)

        user  = await user_repo.get_by_id(callback.from_user.id)
        house = await house_repo.get_by_id(user.house_id)

        # Resurs yetarlimi?
        if (soldiers  > house.total_soldiers or
            dragons   > house.total_dragons  or
            scorpions > house.total_scorpions):
            await callback.answer("❌ Yetarli resurs yo'q (boshqa urushga yuborilgan bo'lishi mumkin).", show_alert=True)
            await state.clear()
            return

        if soldiers == 0 and dragons == 0 and scorpions == 0:
            # Auto-defend — resurs ayirilmaydi, faqat belgi qo'yiladi
            await dep_repo.set_auto_defend(war_id, user.house_id)
            await state.clear()
            await callback.answer()
            await callback.message.answer(
                "🛡️ <b>Avtomatik mudofaa belgilandi!</b>\n"
                "Jang paytida mavjud barcha resurslaringiz ishlatiladi.",
                parse_mode="HTML"
            )
            return

        # Xonadon balansidan ayirish
        await house_repo.update_military(
            user.house_id,
            soldiers=-soldiers,
            dragons=-dragons,
            scorpions=-scorpions
        )

        # Deployment yozish — ustiga qo'shish
        existing = await dep_repo.get_deployment(war_id, user.house_id)
        if existing and not existing.is_auto_defend:
            await dep_repo.upsert(
                war_id, user.house_id,
                existing.soldiers  + soldiers,
                existing.dragons   + dragons,
                existing.scorpions + scorpions
            )
        else:
            await dep_repo.upsert(war_id, user.house_id, soldiers, dragons, scorpions)

        # Raqibga xabar (miqdor ko'rsatilmaydi — strategiya saqlanadi)
        war = await war_repo.get_by_id(war_id)
        enemy_house_id = (
            war.defender_house_id
            if war.attacker_house_id == user.house_id
            else war.attacker_house_id
        )
        enemy_house = await house_repo.get_by_id(enemy_house_id)
        if enemy_house and enemy_house.lord_id:
            try:
                await callback.bot.send_message(
                    enemy_house.lord_id,
                    "⚔️ Dushman resurslarini jangga yubordi!"
                )
            except Exception:
                pass

    await state.clear()
    await callback.answer()
    await callback.message.answer(
        f"✅ <b>Resurslar yuborildi!</b>\n\n"
        f"🗡️ {soldiers} askar | 🐉 {dragons} ajdar | 🏹 {scorpions} skorpion\n\n"
        f"Jang natijasini kuting.",
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("deploy:cancel:"))
async def deploy_cancel_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await callback.message.answer("❌ Resurs yuborish bekor qilindi.")


@router.callback_query(F.data.startswith("deploy:status:"))
async def deploy_status_handler(callback: CallbackQuery):
    war_id = int(callback.data.split(":")[2])

    async with AsyncSessionFactory() as session:
        user_repo  = UserRepo(session)
        dep_repo   = WarDeploymentRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)

        if not user or not user.house_id:
            await callback.answer("❌ Xonadon topilmadi.", show_alert=True)
            return

        dep = await dep_repo.get_deployment(war_id, user.house_id)
        if not dep:
            await callback.answer("Hali resurs yubormagansiz.", show_alert=True)
            return

        if dep.is_auto_defend:
            text = "🛡️ <b>Avtomatik mudofaa</b> — jangda barcha resurslaringiz ishlatiladi."
        else:
            text = (
                f"📦 <b>Yuborilgan resurslar:</b>\n\n"
                f"🗡️ Askar: {dep.soldiers}\n"
                f"🐉 Ajdar: {dep.dragons}\n"
                f"🏹 Skorpion: {dep.scorpions}"
            )

    await callback.answer()
    await callback.message.answer(text, parse_mode="HTML")
