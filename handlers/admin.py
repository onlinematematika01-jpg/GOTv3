from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from database.engine import AsyncSessionFactory
from database.repositories import UserRepo, HouseRepo, MarketRepo, BotSettingsRepo, HouseResourcesRepo
from database.models import RoleEnum, RegionEnum, House
from keyboards import admin_keyboard, back_only_keyboard
from config.settings import settings
from sqlalchemy import select, update, delete, text
from sqlalchemy.orm import selectinload
from database.models import User, MarketPrice, IronBankLoan, Alliance, War, Chronicle, InternalMessage, WarAllySupport, HukmdorClaim, HukmdorClaimResponse, UserCustomItem, HouseCustomItem

router = Router()

ADMIN_IDS: list[int] = settings.ADMIN_IDS


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


class AdminState(StatesGroup):
    waiting_price_item = State()
    waiting_price_value = State()
    waiting_interest = State()
    waiting_broadcast = State()
    waiting_give_gold_user = State()
    waiting_give_gold_amount = State()
    # Yangi xonadon qo'shish
    waiting_house_name = State()
    waiting_house_region = State()
    # Bank limit sozlash
    waiting_bank_min = State()
    waiting_bank_max = State()
    # Farm jadvali
    waiting_farm_time = State()
    waiting_farm_amount = State()
    # Qarzdorlar boshqaruvi
    waiting_debt_extend_days = State()
    waiting_debt_confiscate = State()
    # Urush seanslar
    waiting_war_session_start = State()
    waiting_war_session_end = State()
    # Custom item qo'shish
    item_name = State()
    item_emoji = State()
    item_type = State()
    item_attack_power = State()
    item_defense_power = State()
    item_price = State()
    item_stock = State()
    # Item boshqaruvi
    item_manage = State()
    item_edit_attack = State()
    item_edit_defense = State()
    item_edit_price = State()
    item_edit_stock = State()
    # Ritsar sozlamalari
    waiting_knight_max_soldiers = State()
    waiting_knight_daily_farm = State()
    waiting_knight_buy_limit = State()
    # Pauza
    waiting_pause_reason = State()
    # Xonadon resurslari tahrirlash
    waiting_house_resource_value = State()


# ─── BANK LIMIT — runtime o'zgaruvchilar ───
BANK_MIN_LOAN = 100
BANK_MAX_LOAN = 100_000


@router.message(F.text == "🔧 Admin Panel")
@router.message(Command("admin"))
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Ruxsat yo'q.")
        return

    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)

        total_users = await session.execute(select(User))
        user_count = len(total_users.scalars().all())

        all_houses = await house_repo.get_all()

    text = (
        "🔧 <b>ADMIN PANEL — Uch Ko'zli Qarg'a</b>\n\n"
        f"👥 Jami foydalanuvchilar: {user_count}\n"
        f"🏰 Jami xonadonlar: {len(all_houses)}\n"
    )
    await message.answer(text, reply_markup=admin_keyboard(), parse_mode="HTML")


# ─── NARXLAR ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:back")
async def admin_back(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return
    async with AsyncSessionFactory() as session:
        from database.repositories import HouseRepo
        house_repo = HouseRepo(session)
        from sqlalchemy import select
        total_users = await session.execute(select(User))
        user_count = len(total_users.scalars().all())
        all_houses = await house_repo.get_all()
    text = (
        "🔧 <b>ADMIN PANEL — Uch Ko'zli Qarg'a</b>\n\n"
        f"👥 Jami foydalanuvchilar: {user_count}\n"
        f"🏰 Jami xonadonlar: {len(all_houses)}\n"
    )
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=admin_keyboard(), parse_mode="HTML")

@router.callback_query(F.data == "admin:prices")
async def admin_prices_menu(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    async with AsyncSessionFactory() as session:
        market_repo = MarketRepo(session)
        prices = await market_repo.get_all_prices()

    await state.set_state(AdminState.waiting_price_item)
    await callback.answer()
    await callback.message.answer(
        f"💰 <b>Narxlarni o'zgartirish</b>\n\n"
        f"Joriy narxlar:\n"
        f"• soldier: {prices.get('soldier', 1)}\n"
        f"• dragon: {prices.get('dragon', 150)}\n"
        f"• scorpion: {prices.get('scorpion', 25)}\n\n"
        f"Qaysi tovar? (soldier / dragon / scorpion):"
    )


@router.message(AdminState.waiting_price_item)
async def admin_price_item(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    item = message.text.strip().lower()
    if item not in ["soldier", "dragon", "scorpion"]:
        await message.answer("❌ Noto'g'ri tovar nomi.")
        return
    await state.update_data(price_item=item)
    await state.set_state(AdminState.waiting_price_value)
    await message.answer(f"✏️ {item} uchun yangi narxni kiriting:")


@router.message(AdminState.waiting_price_value)
async def admin_price_value(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        new_price = int(message.text.strip())
        if new_price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Musbat raqam kiriting.")
        return

    data = await state.get_data()
    item = data["price_item"]

    async with AsyncSessionFactory() as session:
        market_repo = MarketRepo(session)
        await market_repo.set_price(item, new_price)

    await message.answer(f"✅ {item} narxi {new_price} tangaga o'zgartirildi!")
    await state.clear()


# ─── BANK FOIZ ─────────────────────────────────────────────────────────────
@router.callback_query(F.data == "admin:interest")
async def admin_interest(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    async with AsyncSessionFactory() as session:
        cfg = BotSettingsRepo(session)
        current_rate = await cfg.get_float("interest_rate")

    await state.set_state(AdminState.waiting_interest)
    await callback.answer()
    await callback.message.answer(
        f"🏦 Joriy foiz: {current_rate * 100:.0f}%\n"
        f"Yangi foizni kiriting (masalan: 15 → 15%):"
    )


@router.message(AdminState.waiting_interest)
async def admin_set_interest(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        rate = float(message.text.strip())
        if rate < 0 or rate > 100:
            raise ValueError
    except ValueError:
        await message.answer("❌ 0 dan 100 gacha raqam kiriting.")
        return

    async with AsyncSessionFactory() as session:
        await BotSettingsRepo(session).set("interest_rate", str(rate / 100))

    await message.answer(f"✅ Foiz stavkasi {rate:.0f}% ga o'zgartirildi va bazaga saqlandi!")
    await state.clear()


# ─── BANK LIMIT (MIN / MAX) ─────────────────────────────────────────────────
@router.callback_query(F.data == "admin:bank_limits")
async def admin_bank_limits(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    async with AsyncSessionFactory() as session:
        cfg = BotSettingsRepo(session)
        cur_min = await cfg.get_int("bank_min_loan")
        cur_max = await cfg.get_int("bank_max_loan")

    await state.set_state(AdminState.waiting_bank_min)
    await callback.answer()
    await callback.message.answer(
        f"🏦 <b>Bank qarz limiti sozlash</b>\n\n"
        f"Joriy minimal qarz: {cur_min:,} tanga\n"
        f"Joriy maksimal qarz: {cur_max:,} tanga\n\n"
        f"Yangi MINIMAL miqdorni kiriting:",
        parse_mode="HTML"
    )


@router.message(AdminState.waiting_bank_min)
async def admin_set_bank_min(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        val = int(message.text.strip())
        if val <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Musbat raqam kiriting.")
        return

    await state.update_data(bank_min=val)
    await state.set_state(AdminState.waiting_bank_max)
    await message.answer(f"✅ Minimal: {val:,} tanga.\n\nEndi MAKSIMAL miqdorni kiriting:")


@router.message(AdminState.waiting_bank_max)
async def admin_set_bank_max(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    try:
        val = int(message.text.strip())
        if val <= data.get("bank_min", 0):
            await message.answer("❌ Maksimal minimal dan katta bo'lishi kerak.")
            return
    except ValueError:
        await message.answer("❌ Musbat raqam kiriting.")
        return

    async with AsyncSessionFactory() as session:
        cfg = BotSettingsRepo(session)
        await cfg.set("bank_min_loan", str(data["bank_min"]))
        await cfg.set("bank_max_loan", str(val))

    await message.answer(
        f"✅ <b>Bank limiti bazaga saqlandi!</b>\n\n"
        f"Minimal: {data['bank_min']:,} tanga\n"
        f"Maksimal: {val:,} tanga",
        parse_mode="HTML"
    )
    await state.clear()


# ─── BROADCAST ─────────────────────────────────────────────────────────────
@router.callback_query(F.data == "admin:broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    await state.set_state(AdminState.waiting_broadcast)
    await callback.answer()
    await callback.message.answer("📢 Barcha foydalanuvchilarga yuboriladigan xabarni yozing:")


@router.message(AdminState.waiting_broadcast)
async def admin_do_broadcast(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    async with AsyncSessionFactory() as session:
        result = await session.execute(select(User).where(User.is_active == True))
        all_users = result.scalars().all()

    sent = 0
    failed = 0
    for user in all_users:
        try:
            await message.bot.send_message(
                user.id,
                f"📢 <b>Admin xabari:</b>\n\n{message.text}",
                parse_mode="HTML"
            )
            sent += 1
        except Exception:
            failed += 1

    await message.answer(
        f"📢 <b>Broadcast yakunlandi!</b>\n"
        f"✅ Yuborildi: {sent}\n"
        f"❌ Yuborilmadi: {failed}",
        parse_mode="HTML"
    )
    await state.clear()


# ─── FOYDALANUVCHILAR ───────────────────────────────────────────────────────
@router.callback_query(F.data == "admin:users")
async def admin_users(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    async with AsyncSessionFactory() as session:
        result = await session.execute(select(User))
        users = result.scalars().all()

        by_role = {}
        for u in users:
            by_role.setdefault(u.role.value, 0)
            by_role[u.role.value] += 1

    text = "👥 <b>Foydalanuvchilar statistikasi:</b>\n\n"
    for role, count in by_role.items():
        text += f"• {role}: {count}\n"
    text += f"\nJami: {len(users)}"

    await callback.answer()
    await callback.message.answer(text, parse_mode="HTML")


# ─── XONADONLAR ────────────────────────────────────────────────────────────
@router.callback_query(F.data == "admin:houses")
async def admin_houses(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    async with AsyncSessionFactory() as session:
        house_repo = HouseRepo(session)
        user_repo = UserRepo(session)
        houses = await house_repo.get_all()

        text = "🏰 <b>Xonadonlar holati:</b>\n\n"
        for h in houses:
            count = await user_repo.count_house_members(h.id)
            lord_name = "—"
            if h.lord_id:
                lord = await user_repo.get_by_id(h.lord_id)
                lord_name = lord.full_name if lord else "—"
            text += (
                f"🏰 <b>{h.name}</b> ({h.region.value})\n"
                f"   👑 Lord: {lord_name} | 👥 {count}/10 | 💰 {h.treasury:,}\n"
            )

    await callback.answer()
    await callback.message.answer(text, reply_markup=back_only_keyboard("admin:back"), parse_mode="HTML")


# ─── YANGI XONADON QO'SHISH ────────────────────────────────────────────────
REGION_LIST = {
    "1": RegionEnum.NORTH,
    "2": RegionEnum.VALE,
    "3": RegionEnum.RIVERLANDS,
    "4": RegionEnum.IRON_ISLANDS,
    "5": RegionEnum.WESTERLANDS,
    "6": RegionEnum.KINGS_LANDING,
    "7": RegionEnum.REACH,
    "8": RegionEnum.STORMLANDS,
    "9": RegionEnum.DORNE,
}

REGION_NAMES = {
    "1": "Shimol",
    "2": "Vodiy",
    "3": "Daryo yerlari",
    "4": "Temir orollar",
    "5": "G'arbiy yerlar",
    "6": "Qirollik bandargohi",
    "7": "Tyrellar vodiysi",
    "8": "Bo'ronli yerlar",
    "9": "Dorn",
}


@router.callback_query(F.data == "admin:add_house")
async def admin_add_house_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    region_text = "\n".join([f"{k}. {v}" for k, v in REGION_NAMES.items()])
    await state.set_state(AdminState.waiting_house_region)
    await callback.answer()
    await callback.message.answer(
        f"🏰 <b>Yangi xonadon qo'shish</b>\n\n"
        f"Xududlar:\n{region_text}\n\n"
        f"Xududning raqamini kiriting:",
        parse_mode="HTML"
    )


@router.message(AdminState.waiting_house_region)
async def admin_add_house_region(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    choice = message.text.strip()
    if choice not in REGION_NAMES:
        await message.answer("❌ Noto'g'ri raqam. 1–9 oralig'ida kiriting.")
        return

    await state.update_data(chosen_region=choice)
    await state.set_state(AdminState.waiting_house_name)
    await message.answer(
        f"✅ Xudud: <b>{REGION_NAMES[choice]}</b>\n\n"
        f"Xonadon nomini kiriting (masalan: Targaryen xonadoni):",
        parse_mode="HTML"
    )


@router.message(AdminState.waiting_house_name)
async def admin_add_house_name(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    name = message.text.strip()
    region_enum = REGION_LIST[data["chosen_region"]]

    async with AsyncSessionFactory() as session:
        new_house = House(name=name, region=region_enum)
        session.add(new_house)
        await session.commit()

    await message.answer(
        f"✅ <b>{name}</b> xonadoni <b>{REGION_NAMES[data['chosen_region']]}</b> xududiga qo'shildi!",
        parse_mode="HTML"
    )
    await state.clear()


# ─── BAZANI TOZALASH ───────────────────────────────────────────────────────
@router.callback_query(F.data == "admin:reset_db")
async def admin_reset_db_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⚠️ HA, TOZALA!", callback_data="admin:reset_db_confirm"),
        InlineKeyboardButton(text="❌ Bekor", callback_data="admin:reset_db_cancel"),
    ]])

    await callback.answer()
    await callback.message.answer(
        "⚠️ <b>DIQQAT!</b>\n\n"
        "Bu amal barcha foydalanuvchilar, urushlar, qarzlar va xronikalarni o'chiradi.\n"
        "Xonadonlar saqlanib qoladi.\n\n"
        "Davom etasizmi?",
        reply_markup=kb,
        parse_mode="HTML"
    )


@router.callback_query(F.data == "admin:reset_db_cancel")
async def admin_reset_cancel(callback: CallbackQuery):
    await callback.answer("Bekor qilindi.", show_alert=True)
    await callback.message.delete()


@router.callback_query(F.data == "admin:reset_db_confirm")
async def admin_reset_db_execute(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    await callback.answer()
    await callback.message.answer("⏳ Baza tozalanmoqda...")

    async with AsyncSessionFactory() as session:
        # 1. Avval xonadonlardagi foreign key larni NULL ga tushirish
        await session.execute(
            update(House).values(
                lord_id=None,
                high_lord_id=None,
                treasury=0,
                total_soldiers=0,
                total_dragons=0,
                total_scorpions=0,
                is_under_occupation=False,
                occupier_house_id=None,
                permanent_tax_rate=0.0,
                vassal_since=None,
            )
        )
        await session.flush()
        # 2. Bog'liq jadvallarni to'g'ri tartibda tozalash (child -> parent)
        await session.execute(delete(UserCustomItem))
        await session.execute(delete(HouseCustomItem))
        await session.execute(delete(IronBankLoan))
        await session.execute(delete(InternalMessage))
        await session.execute(delete(Chronicle))
        await session.execute(delete(WarAllySupport))
        await session.execute(delete(War))
        await session.execute(delete(HukmdorClaimResponse))
        await session.execute(delete(HukmdorClaim))
        await session.execute(delete(Alliance))
        await session.flush()
        # 3. Foydalanuvchilarni o'chirish
        await session.execute(delete(User))
        await session.commit()

    await callback.message.answer(
        "✅ <b>Baza tozalandi!</b>\n\n"
        "Foydalanuvchilar, urushlar, qarzlar va xronikalar o'chirildi.\n"
        "Xonadonlar saqlanib qoldi (reset holatida).",
        parse_mode="HTML"
    )


# ─── OLTIN BERISH ──────────────────────────────────────────────────────────
@router.message(Command("give_gold"))
async def admin_give_gold(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("Ishlatish: /give_gold <user_id> <miqdor>")
        return

    try:
        target_id = int(parts[1])
        amount = int(parts[2])
    except ValueError:
        await message.answer("❌ Noto'g'ri format.")
        return

    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        target = await user_repo.get_by_id(target_id)
        if not target:
            await message.answer("❌ Foydalanuvchi topilmadi.")
            return
        await user_repo.update_gold(target_id, amount)

    await message.answer(f"✅ {target.full_name} ga {amount} oltin berildi!")
    try:
        await message.bot.send_message(target_id, f"🎁 Admindan {amount} oltin sovg'a qilindi!")
    except Exception:
        pass


# ─── FARM JADVALI ──────────────────────────────────────────────────────────

def _fmt_schedules(schedules: list[dict]) -> str:
    if not schedules:
        return "📭 Hozircha farm jadvali yo'q."
    lines = []
    for i, s in enumerate(schedules, 1):
        lines.append(f"{i}. 🕐 {s['hour']:02d}:{s['minute']:02d} — 💰 {s['amount']} tanga")
    return "🌾 <b>Joriy farm jadvali:</b>\n\n" + "\n".join(lines)


@router.callback_query(F.data == "admin:farm_schedule")
async def admin_farm_schedule(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    async with AsyncSessionFactory() as session:
        cfg = BotSettingsRepo(session)
        schedules = await cfg.get_farm_schedules()

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Yangi vaqt qo'shish", callback_data="admin:farm_add")],
        [InlineKeyboardButton(text="🗑 Vaqt o'chirish", callback_data="admin:farm_delete")],
        [InlineKeyboardButton(text="◀️ Orqaga", callback_data="admin:back")],
    ])

    await callback.answer()
    await callback.message.answer(
        _fmt_schedules(schedules) + "\n\nNima qilmoqchisiz?",
        reply_markup=kb,
        parse_mode="HTML"
    )


@router.callback_query(F.data == "admin:farm_add")
async def admin_farm_add(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    await state.set_state(AdminState.waiting_farm_time)
    await callback.answer()
    await callback.message.answer(
        "🕐 <b>Yangi farm vaqtini kiriting</b>\n\n"
        "Format: <code>SS:MM</code>\n"
        "Masalan: <code>08:00</code> yoki <code>14:30</code>",
        parse_mode="HTML"
    )


@router.message(AdminState.waiting_farm_time)
async def admin_farm_time(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    text = message.text.strip()
    try:
        parts = text.split(":")
        if len(parts) != 2:
            raise ValueError
        hour = int(parts[0])
        minute = int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except ValueError:
        await message.answer("❌ Noto'g'ri format. SS:MM ko'rinishida kiriting (masalan: 08:00).")
        return

    await state.update_data(farm_hour=hour, farm_minute=minute)
    await state.set_state(AdminState.waiting_farm_amount)
    await message.answer(
        f"✅ Vaqt: <b>{hour:02d}:{minute:02d}</b>\n\n"
        f"💰 Endi farm miqdorini kiriting (tanga):\n"
        f"Masalan: <code>50</code> yoki <code>150</code>",
        parse_mode="HTML"
    )


@router.message(AdminState.waiting_farm_amount)
async def admin_farm_amount(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    try:
        amount = int(message.text.strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Musbat raqam kiriting.")
        return

    data = await state.get_data()
    hour = data["farm_hour"]
    minute = data["farm_minute"]

    async with AsyncSessionFactory() as session:
        cfg = BotSettingsRepo(session)
        schedules = await cfg.get_farm_schedules()

        existing = next((s for s in schedules if s["hour"] == hour and s["minute"] == minute), None)
        if existing:
            existing["amount"] = amount
        else:
            schedules.append({"hour": hour, "minute": minute, "amount": amount})

        schedules.sort(key=lambda s: (s["hour"], s["minute"]))
        await cfg.set_farm_schedules(schedules)

    from utils.scheduler import reload_farm_jobs
    await reload_farm_jobs(message.bot)

    await message.answer(
        f"✅ <b>Farm jadvali yangilandi!</b>\n\n"
        f"🕐 {hour:02d}:{minute:02d} — 💰 {amount} tanga qo'shildi.\n\n"
        f"{_fmt_schedules(schedules)}",
        parse_mode="HTML"
    )
    await state.clear()


@router.callback_query(F.data == "admin:farm_delete")
async def admin_farm_delete(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    async with AsyncSessionFactory() as session:
        cfg = BotSettingsRepo(session)
        schedules = await cfg.get_farm_schedules()

    if not schedules:
        await callback.answer("📭 Jadval bo'sh.", show_alert=True)
        return

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    buttons = []
    for i, s in enumerate(schedules):
        label = f"🗑 {s['hour']:02d}:{s['minute']:02d} — {s['amount']} tanga"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"admin:farm_del_{i}")])
    buttons.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="admin:farm_schedule")])

    await callback.answer()
    await callback.message.answer(
        "🗑 <b>Qaysi vaqtni o'chirmoqchisiz?</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("admin:farm_del_"))
async def admin_farm_del_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    idx = int(callback.data.split("_")[-1])

    async with AsyncSessionFactory() as session:
        cfg = BotSettingsRepo(session)
        schedules = await cfg.get_farm_schedules()

        if idx >= len(schedules):
            await callback.answer("❌ Topilmadi.", show_alert=True)
            return

        removed = schedules.pop(idx)
        await cfg.set_farm_schedules(schedules)

    from utils.scheduler import reload_farm_jobs
    await reload_farm_jobs(callback.bot)

    await callback.answer()
    await callback.message.answer(
        f"✅ <b>{removed['hour']:02d}:{removed['minute']:02d} — {removed['amount']} tanga</b> o'chirildi.\n\n"
        f"{_fmt_schedules(schedules)}",
        parse_mode="HTML"
    )


# ─── QARZDORLAR BOSHQARUVI ──────────────────────────────────────────────────

from database.repositories import IronBankRepo
from datetime import datetime, timezone as tz, timedelta as td


def _fmt_loan_list(loans, houses: dict) -> str:
    if not loans:
        return "✅ Hozirda to'lanmagan qarz yo'q."
    now = datetime.utcnow()
    lines = []
    for loan in loans:
        house_name = houses.get(loan.house_id, f"Xonadon#{loan.house_id}")
        due = loan.due_date
        if due:
            delta = due - now
            overdue = delta.total_seconds() < 0
            due_local = (due + td(hours=5)).strftime("%d.%m %H:%M")
            status = "🔴 Muddati o'tgan" if overdue else f"⏳ {due_local} gacha"
        else:
            status = "❓ Muddat belgilanmagan"
        lines.append(
            f"🏰 <b>{house_name}</b>\n"
            f"   💰 Qarz: {loan.total_due:,} tanga\n"
            f"   {status}"
        )
    return "\n\n".join(lines)


@router.callback_query(F.data == "admin:debtors")
async def admin_debtors(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    async with AsyncSessionFactory() as session:
        iron_repo = IronBankRepo(session)
        house_repo = HouseRepo(session)
        user_repo = UserRepo(session)
        loans = await iron_repo.get_all_active_loans()

        # house_id yo'q bo'lgan qarzlarda user orqali xonadoni topamiz
        # va house_id ni DB da ham yangilaymiz
        houses = {}
        for loan in loans:
            if not loan.house_id:
                user = await user_repo.get_by_id(loan.user_id)
                if user and user.house_id:
                    # DB da ham yangilaymiz
                    await session.execute(
                        update(IronBankLoan).where(IronBankLoan.id == loan.id).values(house_id=user.house_id)
                    )
                    loan.house_id = user.house_id
                    await session.commit()
            if loan.house_id and loan.house_id not in houses:
                h = await house_repo.get_by_id(loan.house_id)
                houses[loan.house_id] = h.name if h else f"#{loan.house_id}"

    # house_id hali ham yo'q bo'lganlarni chiqarib tashlaymiz
    loans = [l for l in loans if l.house_id]

    if not loans:
        await callback.answer()
        await callback.message.answer(
            "✅ Hozirda to'lanmagan qarz yo'q.",
            reply_markup=back_only_keyboard("admin:back")
        )
        return

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    buttons = []
    seen_houses = set()
    for loan in loans:
        if loan.house_id in seen_houses:
            continue
        seen_houses.add(loan.house_id)
        house_name = houses.get(loan.house_id, f"#{loan.house_id}")
        buttons.append([InlineKeyboardButton(
            text=f"🏰 {house_name} — {loan.total_due:,} tanga",
            callback_data=f"admin:debt_detail:{loan.house_id}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="admin:back")])

    await callback.answer()
    await callback.message.answer(
        f"💸 <b>QARZDORLAR RO'YXATI</b>\n\n"
        f"{_fmt_loan_list(loans, houses)}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("admin:debt_detail:"))
async def admin_debt_detail(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    house_id = int(callback.data.split(":")[-1])

    async with AsyncSessionFactory() as session:
        house_repo = HouseRepo(session)
        iron_repo = IronBankRepo(session)
        house = await house_repo.get_by_id(house_id)
        debt = await iron_repo.get_house_active_debt(house_id)

    if not house:
        await callback.answer("❌ Xonadon topilmadi.", show_alert=True)
        return

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Muddatni uzaytirish", callback_data=f"admin:debt_extend:{house_id}")],
        [InlineKeyboardButton(text="⚔️ Resurs musodara qilish", callback_data=f"admin:debt_confiscate:{house_id}")],
        [InlineKeyboardButton(text="🎁 Qarzni kechirish", callback_data=f"admin:debt_forgive:{house_id}")],
        [InlineKeyboardButton(text="◀️ Orqaga", callback_data="admin:debtors")],
    ])

    await callback.answer()
    await callback.message.answer(
        f"🏰 <b>{house.name}</b>\n\n"
        f"💰 Xazina: {house.treasury:,} tanga\n"
        f"🗡️ Askarlar: {house.total_soldiers:,}\n"
        f"🐉 Ajdarlar: {house.total_dragons}\n"
        f"🏹 Skorpionlar: {house.total_scorpions}\n\n"
        f"🏦 <b>To'lanmagan qarz: {debt:,} tanga</b>\n\n"
        f"Qanday chora ko'rmoqchisiz?",
        reply_markup=kb,
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("admin:debt_extend:"))
async def admin_debt_extend_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    house_id = int(callback.data.split(":")[-1])
    await state.set_state(AdminState.waiting_debt_extend_days)
    await state.update_data(debt_house_id=house_id)
    await callback.answer()
    await callback.message.answer(
        "📅 <b>Necha kun uzaytirmoqchisiz?</b>\n"
        "Masalan: <code>3</code> yoki <code>7</code>",
        parse_mode="HTML"
    )


@router.message(AdminState.waiting_debt_extend_days)
async def admin_debt_extend_confirm(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        days = int(message.text.strip())
        if days <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Musbat son kiriting.")
        return

    data = await state.get_data()
    house_id = data["debt_house_id"]

    async with AsyncSessionFactory() as session:
        iron_repo = IronBankRepo(session)
        house_repo = HouseRepo(session)
        await iron_repo.extend_due_date(house_id, days)
        house = await house_repo.get_by_id(house_id)
        # Lordga xabar
        if house and house.lord_id:
            try:
                await message.bot.send_message(
                    house.lord_id,
                    f"🏦 <b>Temir Bank xabari</b>\n\n"
                    f"Qarzingiz muddati <b>{days} kun</b> uzaytirildi.",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    await state.clear()
    await message.answer(
        f"✅ <b>{days} kun</b> uzaytirildi.",
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("admin:debt_confiscate:"))
async def admin_debt_confiscate_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    house_id = int(callback.data.split(":")[-1])

    async with AsyncSessionFactory() as session:
        house_repo = HouseRepo(session)
        iron_repo = IronBankRepo(session)
        house = await house_repo.get_by_id(house_id)
        debt = await iron_repo.get_house_active_debt(house_id)

    await state.set_state(AdminState.waiting_debt_confiscate)
    await state.update_data(debt_house_id=house_id)
    await callback.answer()
    await callback.message.answer(
        f"⚔️ <b>Resurs musodara — {house.name}</b>\n\n"
        f"Joriy resurslar:\n"
        f"🗡️ Askarlar: {house.total_soldiers:,}\n"
        f"🐉 Ajdarlar: {house.total_dragons}\n"
        f"🏹 Skorpionlar: {house.total_scorpions}\n"
        f"💰 Xazina: {house.treasury:,}\n\n"
        f"🏦 Qarz: {debt:,} tanga\n\n"
        f"Quyidagi formatda kiriting:\n"
        f"<code>askar:500 ajdar:2 skorpion:10 oltin:1000</code>\n"
        f"(Kerak bo'lmagan turni o'tkazib yuboring)",
        parse_mode="HTML"
    )


@router.message(AdminState.waiting_debt_confiscate)
async def admin_debt_confiscate_confirm(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    house_id = data["debt_house_id"]

    confiscate = {"soldiers": 0, "dragons": 0, "scorpions": 0, "gold": 0}
    key_map = {"askar": "soldiers", "ajdar": "dragons", "skorpion": "scorpions", "oltin": "gold"}

    try:
        for part in message.text.strip().split():
            if ":" in part:
                k, v = part.split(":", 1)
                if k in key_map:
                    confiscate[key_map[k]] = int(v)
    except Exception:
        await message.answer("❌ Format noto'g'ri. Masalan: <code>askar:500 ajdar:2</code>", parse_mode="HTML")
        return

    if all(v == 0 for v in confiscate.values()):
        await message.answer("❌ Hech narsa tanlanmadi.")
        return

    async with AsyncSessionFactory() as session:
        iron_repo = IronBankRepo(session)
        house_repo = HouseRepo(session)
        value = await iron_repo.confiscate_partial(house_id, confiscate)
        house = await house_repo.get_by_id(house_id)
        remaining = await iron_repo.get_house_active_debt(house_id)

        if house and house.lord_id:
            parts = []
            if confiscate["soldiers"]: parts.append(f"🗡️ {confiscate['soldiers']} askar")
            if confiscate["dragons"]: parts.append(f"🐉 {confiscate['dragons']} ajdar")
            if confiscate["scorpions"]: parts.append(f"🏹 {confiscate['scorpions']} skorpion")
            if confiscate["gold"]: parts.append(f"💰 {confiscate['gold']} tanga")
            try:
                await message.bot.send_message(
                    house.lord_id,
                    f"🏦 <b>Temir Bank musodara qildi!</b>\n\n"
                    f"Qarz undirish maqsadida:\n" + "\n".join(parts) +
                    f"\n\n💸 Qoplandi: {value:,} tanga\n"
                    f"🏦 Qolgan qarz: {remaining:,} tanga",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    await state.clear()
    await message.answer(
        f"✅ <b>Musodara bajarildi</b>\n\n"
        f"💸 Qoplandi: {value:,} tanga\n"
        f"🏦 Qolgan qarz: {remaining:,} tanga",
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("admin:debt_forgive:"))
async def admin_debt_forgive(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    house_id = int(callback.data.split(":")[-1])

    async with AsyncSessionFactory() as session:
        iron_repo = IronBankRepo(session)
        house_repo = HouseRepo(session)
        house = await house_repo.get_by_id(house_id)
        await iron_repo.forgive_debt(house_id)

        if house and house.lord_id:
            try:
                await callback.bot.send_message(
                    house.lord_id,
                    f"🏦 <b>Temir Bank xabari</b>\n\n"
                    f"Xonadoningizning barcha qarzlari kechirildi! 🎉",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    await callback.answer()
    await callback.message.answer(
        f"✅ <b>{house.name}</b> xonadonining qarzi kechirildi.",
        parse_mode="HTML"
    )


# ─── A'ZO KO'CHIRISH ───────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:transfer_member")
async def admin_transfer_start(callback: CallbackQuery, state: FSMContext):
    """A'zo ko'chirish — avval foydalanuvchi ID so'raydi"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return
    await state.set_state("transfer_user_id")
    await callback.message.answer(
        "🔀 <b>A'zo Ko'chirish</b>\n\n"
        "Ko'chirmoqchi bo'lgan foydalanuvchining Telegram ID sini kiriting:",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(StateFilter("transfer_user_id"))
async def admin_transfer_get_user(message: Message, state: FSMContext):
    """Foydalanuvchi ID ni oladi va xonadonlar ro'yxatini ko'rsatadi"""
    if not is_admin(message.from_user.id):
        return
    try:
        user_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Noto'g'ri ID. Raqam kiriting.")
        return

    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)
        user = await user_repo.get_by_id(user_id)

        if not user:
            await message.answer("❌ Bu ID li foydalanuvchi topilmadi.")
            return
        if not user.house_id:
            await message.answer("❌ Bu foydalanuvchi hech bir xonadonda emas.")
            return

        current_house = await house_repo.get_by_id(user.house_id)
        all_houses = await house_repo.get_all()
        other_houses = [h for h in all_houses if h.id != user.house_id]

        if not other_houses:
            await message.answer("❌ Ko'chirish uchun boshqa xonadon yo'q.")
            return

        await state.update_data(transfer_user_id=user_id)
        await state.set_state("transfer_house_id")

        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        buttons = [
            [InlineKeyboardButton(
                text=f"🏰 {h.name} ({h.region.value})",
                callback_data=f"transfer_to:{h.id}"
            )]
            for h in other_houses
        ]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        await message.answer(
            f"👤 <b>{user.full_name}</b>\n"
            f"Hozirgi xonadon: <b>{current_house.name if current_house else '—'}</b>\n"
            f"Roli: <b>{user.role.value}</b>\n\n"
            f"Qaysi xonadonga ko'chirish kerak?",
            reply_markup=keyboard,
            parse_mode="HTML"
        )


@router.callback_query(F.data.startswith("transfer_to:"))
async def admin_transfer_execute(callback: CallbackQuery, state: FSMContext):
    """Ko'chirishni amalga oshiradi + auto-lord mexanikasi"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    data = await state.get_data()
    user_id = data.get("transfer_user_id")
    target_house_id = int(callback.data.split(":")[1])

    async with AsyncSessionFactory() as session:
        from sqlalchemy import select as sa_select, update as sa_update
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)

        user = await user_repo.get_by_id(user_id)
        if not user:
            await callback.answer("❌ Foydalanuvchi topilmadi.", show_alert=True)
            return

        old_house_id = user.house_id
        old_house = await house_repo.get_by_id(old_house_id) if old_house_id else None
        target_house = await house_repo.get_by_id(target_house_id)

        if not target_house:
            await callback.answer("❌ Xonadon topilmadi.", show_alert=True)
            return

        was_lord = (user.role in [RoleEnum.LORD, RoleEnum.HIGH_LORD] and
                    old_house and old_house.lord_id == user.id)

        # ═══ ESKI UYDA AUTO-LORD ═══
        auto_promoted_name = None
        if was_lord and old_house:
            # Lordni uydan chiqaramiz
            await session.execute(
                sa_update(House).where(House.id == old_house_id).values(lord_id=None)
            )
            await session.flush()

            # Eski uyda qolgan birinchi a'zoni lord qilamiz
            members_result = await session.execute(
                sa_select(User).where(
                    User.house_id == old_house_id,
                    User.id != user_id,
                    User.is_active == True,
                    User.role != RoleEnum.ADMIN
                ).order_by(User.id)
            )
            remaining = members_result.scalars().first()
            if remaining:
                await session.execute(
                    sa_update(User).where(User.id == remaining.id).values(role=RoleEnum.LORD)
                )
                await session.execute(
                    sa_update(House).where(House.id == old_house_id).values(lord_id=remaining.id)
                )
                auto_promoted_name = remaining.full_name
                # Yangi lordga xabar
                try:
                    await callback.bot.send_message(
                        remaining.id,
                        f"👑 <b>Siz {old_house.name} xonadonining yangi Lordi bo'ldingiz!</b>\n\n"
                        f"Admin tomonidan ko'chirish natijasida avvalgi lord ketdi.",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

        # ═══ YANGI UYGA KO'CHIRISH ═══
        # Yangi uyda lord bormi?
        new_role = RoleEnum.LORD if not target_house.lord_id else RoleEnum.MEMBER

        # Foydalanuvchining shaxsiy resurs va qarz maydonlarini nolga tushiramiz
        # (resurslar xonadonnikiga o'tadi, shaxsiy qator eskirgan ma'lumot bo'lmasin)
        await session.execute(
            sa_update(User).where(User.id == user_id).values(
                house_id=target_house_id,
                region=target_house.region,
                role=new_role,
                soldiers=0,
                dragons=0,
                scorpions=0,
                debt=0,
            )
        )
        if new_role == RoleEnum.LORD:
            await session.execute(
                sa_update(House).where(House.id == target_house_id).values(lord_id=user_id)
            )

        await session.commit()

        # Natija xabari
        result_text = (
            f"✅ <b>Ko'chirish amalga oshirildi!</b>\n\n"
            f"👤 {user.full_name}\n"
            f"🏠 {old_house.name if old_house else '—'} → {target_house.name}\n"
            f"👑 Yangi roli: <b>{new_role.value}</b>\n"
        )
        if auto_promoted_name:
            result_text += f"\n🔄 <b>{old_house.name}</b> da yangi lord: <b>{auto_promoted_name}</b>"
        elif was_lord and old_house:
            result_text += f"\n⚠️ <b>{old_house.name}</b> da lord yo'q (a'zo qolmadi)"

        await callback.message.answer(result_text, parse_mode="HTML")

        # Ko'chirilgan foydalanuvchiga xabar
        try:
            await callback.bot.send_message(
                user_id,
                f"🔀 <b>Siz boshqa xonadonga ko'childingiz!</b>\n\n"
                f"🏰 Yangi xonadon: <b>{target_house.name}</b>\n"
                f"👑 Rolingiz: <b>{new_role.value}</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass

    await state.clear()
    await callback.answer()


# ─── URUSH SEANSLAR ────────────────────────────────────────────────────────

def _fmt_war_sessions(sessions: list[dict]) -> str:
    if not sessions:
        return "⚔️ <b>Urush Seanslar</b>\n\nHech qanday seans yo'q."
    lines = ["⚔️ <b>Urush Seanslar</b>\n"]
    for i, s in enumerate(sessions, 1):
        deadline = s.get("declare_deadline", s["end"] - 1)
        lines.append(f"{i}. 🕐 {s['start']:02d}:00 – {s['end']:02d}:00  (e'lon: {s['start']:02d}:00–{deadline:02d}:00)")
    return "\n".join(lines)


@router.callback_query(F.data == "admin:war_sessions")
async def admin_war_sessions(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    async with AsyncSessionFactory() as session:
        cfg = BotSettingsRepo(session)
        sessions = await cfg.get_war_sessions()

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Seans qo'shish", callback_data="admin:war_session_add")],
        [InlineKeyboardButton(text="🗑 Seans o'chirish", callback_data="admin:war_session_delete")],
        [InlineKeyboardButton(text="◀️ Orqaga", callback_data="admin:back")],
    ])
    await callback.answer()
    await callback.message.answer(
        _fmt_war_sessions(sessions) + "\n\nNima qilmoqchisiz?",
        reply_markup=kb,
        parse_mode="HTML"
    )


@router.callback_query(F.data == "admin:war_session_add")
async def admin_war_session_add(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return
    await state.set_state(AdminState.waiting_war_session_start)
    await callback.answer()
    await callback.message.answer(
        "⚔️ <b>Yangi urush seansi</b>\n\n"
        "Boshlanish vaqtini kiriting (soat, 0–23):\n"
        "Masalan: <code>19</code>",
        parse_mode="HTML"
    )


@router.message(AdminState.waiting_war_session_start)
async def admin_war_session_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        hour = int(message.text.strip())
        if not (0 <= hour <= 23):
            raise ValueError
    except ValueError:
        await message.answer("❌ 0 dan 23 gacha raqam kiriting.")
        return

    await state.update_data(war_start=hour)
    await state.set_state(AdminState.waiting_war_session_end)
    await message.answer(
        f"✅ Boshlanish: <b>{hour:02d}:00</b>\n\n"
        f"Tugash vaqtini kiriting (soat, {hour+1}–23):\n"
        f"Masalan: <code>23</code>",
        parse_mode="HTML"
    )


@router.message(AdminState.waiting_war_session_end)
async def admin_war_session_end(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    war_start = data["war_start"]

    try:
        hour = int(message.text.strip())
        if not (war_start < hour <= 23):
            raise ValueError
    except ValueError:
        await message.answer(f"❌ {war_start+1} dan 23 gacha raqam kiriting.")
        return

    declare_deadline = hour - 1  # E'lon qilish oxirgi soati (tugashdan 1 soat oldin)

    async with AsyncSessionFactory() as session:
        cfg = BotSettingsRepo(session)
        sessions = await cfg.get_war_sessions()
        sessions.append({
            "start": war_start,
            "end": hour,
            "declare_deadline": declare_deadline
        })
        await cfg.set_war_sessions(sessions)

    await state.clear()
    await message.answer(
        f"✅ <b>Urush seansi qo'shildi!</b>\n\n"
        f"🕐 {war_start:02d}:00 – {hour:02d}:00\n"
        f"E'lon qilish: {war_start:02d}:00 – {declare_deadline:02d}:00",
        parse_mode="HTML"
    )


@router.callback_query(F.data == "admin:war_session_delete")
async def admin_war_session_delete(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    async with AsyncSessionFactory() as session:
        cfg = BotSettingsRepo(session)
        sessions = await cfg.get_war_sessions()

    if not sessions:
        await callback.answer("Seanslar yo'q.", show_alert=True)
        return

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    buttons = [
        [InlineKeyboardButton(
            text=f"🗑 {s['start']:02d}:00–{s['end']:02d}:00",
            callback_data=f"admin:war_session_del:{i}"
        )]
        for i, s in enumerate(sessions)
    ]
    buttons.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="admin:war_sessions")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.answer()
    await callback.message.answer("Qaysi seansi o'chirmoqchisiz?", reply_markup=kb)


@router.callback_query(F.data.startswith("admin:war_session_del:"))
async def admin_war_session_del_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    idx = int(callback.data.split(":")[-1])

    async with AsyncSessionFactory() as session:
        cfg = BotSettingsRepo(session)
        sessions = await cfg.get_war_sessions()
        if idx < 0 or idx >= len(sessions):
            await callback.answer("❌ Seans topilmadi.", show_alert=True)
            return
        removed = sessions.pop(idx)
        await cfg.set_war_sessions(sessions)

    await callback.answer()
    await callback.message.answer(
        f"✅ Seans o'chirildi: <b>{removed['start']:02d}:00 – {removed['end']:02d}:00</b>",
        parse_mode="HTML"
    )


# ═══════════════════════════════════════════════════════════════════════════
# MAXSUS ITEMLAR (Custom Items)
# ═══════════════════════════════════════════════════════════════════════════

from database.repositories import CustomItemRepo
from database.models import ItemTypeEnum
from keyboards.keyboards import custom_items_menu_keyboard, item_type_keyboard, item_manage_keyboard, item_edit_keyboard

ITEM_TYPE_LABELS = {
    ItemTypeEnum.ATTACK:  "🐉 Hujum",
    ItemTypeEnum.DEFENSE: "🏹 Mudofaa",
    ItemTypeEnum.SOLDIER: "🗡️ Askar (qo'shma)",
}


@router.callback_query(F.data == "admin:custom_items")
async def admin_custom_items_menu(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(
        "🧪 <b>Maxsus Itemlar Boshqaruvi</b>\n\n"
        "Bu yerdan yangi qurol/birlik turlarini qo'shishingiz,\n"
        "mavjudlarini boshqarishingiz mumkin.",
        reply_markup=custom_items_menu_keyboard(),
        parse_mode="HTML",
    )


# ── YANGI ITEM QO'SHISH ────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:item:add")
async def item_add_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return
    await state.set_state(AdminState.item_name)
    await callback.answer()
    await callback.message.edit_text(
        "➕ <b>Yangi Item Qo'shish</b>\n\n"
        "1️⃣ Item nomini yozing:\n"
        "<i>(masalan: Ballista, Troll, Qasrchi)</i>",
        parse_mode="HTML",
    )


@router.message(AdminState.item_name)
async def item_add_name(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    name = message.text.strip()
    if len(name) < 2 or len(name) > 50:
        await message.answer("❌ Nom 2–50 ta belgidan iborat bo'lishi kerak.")
        return
    await state.update_data(item_name=name)
    await state.set_state(AdminState.item_emoji)
    await message.answer(
        f"✅ Nom: <b>{name}</b>\n\n"
        "2️⃣ Item emoji belgisini yuboring:\n"
        "<i>(masalan: 🏹 🐗 🧨 🪃 — bitta emoji)</i>",
        parse_mode="HTML",
    )


@router.message(AdminState.item_emoji)
async def item_add_emoji(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    emoji = message.text.strip()
    await state.update_data(item_emoji=emoji)
    await state.set_state(AdminState.item_type)
    await message.answer(
        f"✅ Emoji: <b>{emoji}</b>\n\n"
        "3️⃣ Item turini tanlang:",
        reply_markup=item_type_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("itype:"))
async def item_add_type(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    itype_str = callback.data.split(":")[1]
    itype_map = {
        "attack":  ItemTypeEnum.ATTACK,
        "defense": ItemTypeEnum.DEFENSE,
        "soldier": ItemTypeEnum.SOLDIER,
    }
    itype = itype_map.get(itype_str)
    if not itype:
        await callback.answer("❌ Noto'g'ri tur.", show_alert=True)
        return

    await state.update_data(item_type=itype_str)
    await state.set_state(AdminState.item_attack_power)
    await callback.answer()

    type_label = ITEM_TYPE_LABELS[itype]
    await callback.message.edit_text(
        f"✅ Tur: <b>{type_label}</b>\n\n"
        "4️⃣ <b>Hujum kuchini</b> kiriting:\n"
        "<i>1 ta bu item nechta askarga teng? (hujumda)</i>\n"
        "<i>Hujum qilmasa — 0 kiriting</i>",
        parse_mode="HTML",
    )


@router.message(AdminState.item_attack_power)
async def item_add_attack(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        val = int(message.text.strip())
        if val < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Musbat son yoki 0 kiriting.")
        return
    await state.update_data(item_attack_power=val)
    await state.set_state(AdminState.item_defense_power)
    await message.answer(
        f"✅ Hujum kuchi: <b>{val}</b> askar ekvivalenti\n\n"
        "5️⃣ <b>Mudofaa kuchini</b> kiriting:\n"
        "<i>1 ta bu item nechta chayonga qarshi tura oladi?</i>\n"
        "<i>Mudofaa qilmasa — 0 kiriting</i>",
        parse_mode="HTML",
    )


@router.message(AdminState.item_defense_power)
async def item_add_defense(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        val = int(message.text.strip())
        if val < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Musbat son yoki 0 kiriting.")
        return
    await state.update_data(item_defense_power=val)
    await state.set_state(AdminState.item_price)
    await message.answer(
        f"✅ Mudofaa kuchi: <b>{val}</b> chayon ekvivalenti\n\n"
        "6️⃣ <b>Narxini</b> kiriting (tanga):",
        parse_mode="HTML",
    )


@router.message(AdminState.item_price)
async def item_add_price(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        price = int(message.text.strip())
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Musbat narx kiriting.")
        return

    await state.update_data(item_price=price)
    await state.set_state(AdminState.item_stock)
    await message.answer(
        f"✅ Narxi: <b>{price:,}</b> tanga\n\n"
        "7️⃣ <b>Maksimal stok miqdorini</b> kiriting:\n"
        "<i>Bu item jami nechta marta sotilishi mumkin?</i>\n"
        "<i>Cheksiz bo'lsa — 0 kiriting</i>",
        parse_mode="HTML",
    )


@router.message(AdminState.item_stock)
async def item_add_stock(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        stock_val = int(message.text.strip())
        if stock_val < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ 0 yoki musbat son kiriting. (0 = cheksiz)")
        return

    max_stock = None if stock_val == 0 else stock_val

    data = await state.get_data()
    name          = data["item_name"]
    emoji         = data["item_emoji"]
    itype_str     = data["item_type"]
    attack_power  = data["item_attack_power"]
    defense_power = data["item_defense_power"]
    price         = data["item_price"]

    itype_map = {
        "attack":  ItemTypeEnum.ATTACK,
        "defense": ItemTypeEnum.DEFENSE,
        "soldier": ItemTypeEnum.SOLDIER,
    }
    itype = itype_map[itype_str]

    async with AsyncSessionFactory() as session:
        repo = CustomItemRepo(session)
        try:
            item = await repo.create_item(
                name=name, emoji=emoji, item_type=itype,
                attack_power=attack_power, defense_power=defense_power,
                price=price, max_stock=max_stock,
            )
        except Exception as e:
            await message.answer(f"❌ Xatolik: {e}")
            await state.clear()
            return

    await state.clear()
    type_label = ITEM_TYPE_LABELS[itype]
    stock_text = f"{max_stock} ta" if max_stock else "♾ Cheksiz"
    await message.answer(
        f"✅ <b>Yangi item yaratildi!</b>\n\n"
        f"{emoji} <b>{name}</b>\n"
        f"📌 Turi: {type_label}\n"
        f"⚔️ Hujum kuchi: {attack_power} askar ekvivalenti\n"
        f"🛡 Mudofaa kuchi: {defense_power} chayon ekvivalenti\n"
        f"💰 Narxi: {price:,} tanga\n"
        f"📦 Stok: {stock_text}\n\n"
        f"Item bozorda aktiv holatda qo'shildi.",
        reply_markup=custom_items_menu_keyboard(),
        parse_mode="HTML",
    )


# ── ITEMLAR RO'YXATI ───────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:item:list")
async def item_list(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    async with AsyncSessionFactory() as session:
        repo = CustomItemRepo(session)
        items = await repo.get_all()

    if not items:
        await callback.answer()
        await callback.message.edit_text(
            "📋 Hozircha maxsus itemlar yo'q.",
            reply_markup=custom_items_menu_keyboard(),
        )
        return

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    lines = ["📋 <b>Barcha Maxsus Itemlar:</b>\n"]
    buttons = []
    for item in items:
        status = "🟢" if item.is_active else "🔴"
        stock_text = "♾" if item.stock_remaining is None else f"📦{item.stock_remaining}"
        lines.append(
            f"{status} {item.emoji} <b>{item.name}</b> — {item.price:,} tanga  {stock_text}\n"
            f"   ⚔️ Hujum: {item.attack_power} | 🛡 Mudofaa: {item.defense_power}"
        )
        buttons.append([InlineKeyboardButton(
            text=f"{item.emoji} {item.name}",
            callback_data=f"admin:item:info:{item.id}"
        )])

    buttons.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin:custom_items")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.answer()
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=keyboard,
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin:item:info:"))
async def item_info(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    item_id = int(callback.data.split(":")[-1])
    async with AsyncSessionFactory() as session:
        repo = CustomItemRepo(session)
        item = await repo.get_by_id(item_id)

    if not item:
        await callback.answer("❌ Item topilmadi.", show_alert=True)
        return

    type_label = ITEM_TYPE_LABELS.get(item.item_type, str(item.item_type))
    status = "🟢 Aktiv" if item.is_active else "🔴 O'chirilgan"
    stock_text = "♾ Cheksiz" if item.stock_remaining is None else f"{item.stock_remaining} / {item.max_stock or '?'}"

    await callback.answer()
    await callback.message.edit_text(
        f"{item.emoji} <b>{item.name}</b>\n\n"
        f"📌 Turi: {type_label}\n"
        f"⚔️ Hujum kuchi: {item.attack_power} askar ekvivalenti\n"
        f"🛡 Mudofaa kuchi: {item.defense_power} chayon ekvivalenti\n"
        f"💰 Narxi: {item.price:,} tanga\n"
        f"📦 Stok: {stock_text}\n"
        f"📊 Holati: {status}",
        reply_markup=item_manage_keyboard(item.id, item.is_active),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin:item:toggle:"))
async def item_toggle(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    item_id = int(callback.data.split(":")[-1])
    async with AsyncSessionFactory() as session:
        repo = CustomItemRepo(session)
        item = await repo.toggle_active(item_id)

    if not item:
        await callback.answer("❌ Item topilmadi.", show_alert=True)
        return

    status = "🟢 Aktiv" if item.is_active else "🔴 O'chirilgan"
    await callback.answer(f"✅ Holat o'zgartirildi: {status}", show_alert=True)
    await item_info(callback)


@router.callback_query(F.data.startswith("admin:item:delete:"))
async def item_delete(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    item_id = int(callback.data.split(":")[-1])
    async with AsyncSessionFactory() as session:
        repo = CustomItemRepo(session)
        item = await repo.get_by_id(item_id)
        if not item:
            await callback.answer("❌ Item topilmadi.", show_alert=True)
            return
        name = item.name
        await repo.delete_item(item_id)

    await callback.answer(f"🗑 '{name}' o'chirildi.", show_alert=True)
    await callback.message.edit_text(
        f"✅ <b>{name}</b> o'chirildi.",
        reply_markup=custom_items_menu_keyboard(),
        parse_mode="HTML",
    )


# ── ITEM TAHRIRLASH ────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("admin:item:edit:") & ~F.data.startswith("admin:item:edit:attack:") & ~F.data.startswith("admin:item:edit:defense:") & ~F.data.startswith("admin:item:edit:price:") & ~F.data.startswith("admin:item:edit:stock:"))
async def item_edit_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return
    item_id = int(callback.data.split(":")[-1])
    async with AsyncSessionFactory() as session:
        repo = CustomItemRepo(session)
        item = await repo.get_by_id(item_id)
    if not item:
        await callback.answer("❌ Item topilmadi.", show_alert=True)
        return
    await callback.answer()
    stock_text = "♾ Cheksiz" if item.stock_remaining is None else f"{item.stock_remaining} / {item.max_stock or '?'}"
    try:
        await callback.message.edit_text(
            f"✏️ <b>{item.emoji} {item.name}</b> — tahrirlash\n\n"
            f"⚔️ Hujum kuchi: <b>{item.attack_power}</b>\n"
            f"🛡 Mudofaa kuchi: <b>{item.defense_power}</b>\n"
            f"💰 Narxi: <b>{item.price:,}</b> tanga\n"
            f"📦 Stok: <b>{stock_text}</b>\n\n"
            f"Qaysi maydonni o'zgartirmoqchisiz?",
            reply_markup=item_edit_keyboard(item_id),
            parse_mode="HTML",
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("admin:item:edit:attack:"))
async def item_edit_attack_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return
    item_id = int(callback.data.split(":")[-1])
    await state.set_state(AdminState.item_edit_attack)
    await state.update_data(edit_item_id=item_id)
    await callback.answer()
    await callback.message.edit_text(
        "⚔️ <b>Yangi hujum kuchini kiriting:</b>\n"
        "(1 ta item nechta askarga teng)",
        parse_mode="HTML",
    )


@router.message(StateFilter(AdminState.item_edit_attack))
async def item_edit_attack_done(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if not message.text or not message.text.isdigit():
        await message.answer("❌ Faqat butun son kiriting.")
        return
    data = await state.get_data()
    item_id = data["edit_item_id"]
    new_val = int(message.text)
    async with AsyncSessionFactory() as session:
        repo = CustomItemRepo(session)
        await repo.update_item(item_id, attack_power=new_val)
        item = await repo.get_by_id(item_id)
    await state.clear()
    await message.answer(
        f"✅ <b>{item.emoji} {item.name}</b>\n"
        f"⚔️ Hujum kuchi: <b>{new_val}</b> ga o'zgartirildi.",
        parse_mode="HTML",
        reply_markup=item_manage_keyboard(item_id, item.is_active),
    )


@router.callback_query(F.data.startswith("admin:item:edit:defense:"))
async def item_edit_defense_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return
    item_id = int(callback.data.split(":")[-1])
    await state.set_state(AdminState.item_edit_defense)
    await state.update_data(edit_item_id=item_id)
    await callback.answer()
    await callback.message.edit_text(
        "🛡 <b>Yangi mudofaa kuchini kiriting:</b>\n"
        "(1 ta item nechta chayonga qarshi tura oladi)",
        parse_mode="HTML",
    )


@router.message(StateFilter(AdminState.item_edit_defense))
async def item_edit_defense_done(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if not message.text or not message.text.isdigit():
        await message.answer("❌ Faqat butun son kiriting.")
        return
    data = await state.get_data()
    item_id = data["edit_item_id"]
    new_val = int(message.text)
    async with AsyncSessionFactory() as session:
        repo = CustomItemRepo(session)
        await repo.update_item(item_id, defense_power=new_val)
        item = await repo.get_by_id(item_id)
    await state.clear()
    await message.answer(
        f"✅ <b>{item.emoji} {item.name}</b>\n"
        f"🛡 Mudofaa kuchi: <b>{new_val}</b> ga o'zgartirildi.",
        parse_mode="HTML",
        reply_markup=item_manage_keyboard(item_id, item.is_active),
    )


@router.callback_query(F.data.startswith("admin:item:edit:price:"))
async def item_edit_price_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return
    item_id = int(callback.data.split(":")[-1])
    await state.set_state(AdminState.item_edit_price)
    await state.update_data(edit_item_id=item_id)
    await callback.answer()
    await callback.message.edit_text(
        "💰 <b>Yangi narxini kiriting (tanga):</b>",
        parse_mode="HTML",
    )


@router.message(StateFilter(AdminState.item_edit_price))
async def item_edit_price_done(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if not message.text or not message.text.isdigit():
        await message.answer("❌ Faqat butun son kiriting.")
        return
    data = await state.get_data()
    item_id = data["edit_item_id"]
    new_val = int(message.text)
    async with AsyncSessionFactory() as session:
        repo = CustomItemRepo(session)
        await repo.update_item(item_id, price=new_val)
        item = await repo.get_by_id(item_id)
    await state.clear()
    await message.answer(
        f"✅ <b>{item.emoji} {item.name}</b>\n"
        f"💰 Narxi: <b>{new_val:,}</b> tangaga o'zgartirildi.",
        parse_mode="HTML",
        reply_markup=item_manage_keyboard(item_id, item.is_active),
    )


@router.callback_query(F.data.startswith("admin:item:edit:stock:"))
async def item_edit_stock_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return
    item_id = int(callback.data.split(":")[-1])
    await state.set_state(AdminState.item_edit_stock)
    await state.update_data(edit_item_id=item_id)
    await callback.answer()
    await callback.message.edit_text(
        "📦 <b>Yangi stok miqdorini kiriting:</b>\n"
        "<i>Jami nechta sotilishi mumkin?</i>\n"
        "<i>Cheksiz bo'lsa — 0 kiriting</i>",
        parse_mode="HTML",
    )


@router.message(StateFilter(AdminState.item_edit_stock))
async def item_edit_stock_done(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        val = int(message.text.strip())
        if val < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ 0 yoki musbat son kiriting.")
        return
    data = await state.get_data()
    item_id = data["edit_item_id"]
    max_stock = None if val == 0 else val
    async with AsyncSessionFactory() as session:
        repo = CustomItemRepo(session)
        await repo.update_item(item_id, max_stock=max_stock, stock_remaining=max_stock)
        item = await repo.get_by_id(item_id)
    await state.clear()
    stock_text = "♾ Cheksiz" if max_stock is None else f"{max_stock} ta"
    await message.answer(
        f"✅ <b>{item.emoji} {item.name}</b>\n"
        f"📦 Stok: <b>{stock_text}</b> ga o'zgartirildi.",
        parse_mode="HTML",
        reply_markup=item_manage_keyboard(item_id, item.is_active),
    )


# ─── Admin: Turnir menyusiga yo'naltirish ─────────────────────────────────────

@router.callback_query(F.data == "admin:tournament")
async def admin_tournament_redirect(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Yangi Turnir Yaratish", callback_data="tourn:create")],
        [InlineKeyboardButton(text="▶️ Turnirni Boshlash",    callback_data="tourn:start")],
        [InlineKeyboardButton(text="🏁 Turnirni Tugatish",    callback_data="tourn:finish")],
        [InlineKeyboardButton(text="📊 Joriy Holat",          callback_data="tourn:status")],
        [InlineKeyboardButton(text="🔙 Orqaga",               callback_data="admin:back")],
    ])
    await callback.message.edit_text("🏆 <b>Turnir Boshqaruvi</b>", reply_markup=kb, parse_mode="HTML")
    await callback.answer()


# ─── Admin: Lord O'ldirish ─────────────────────────────────────────────────────
import asyncio

@router.callback_query(F.data == "admin:kill_lord")
async def admin_kill_lord_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(User).where(
                User.role == RoleEnum.LORD,
                User.is_active == True
            ).options(selectinload(User.house))
        )
        lords = result.scalars().all()

    if not lords:
        await callback.answer("❌ Hozirda lordlar yo'q.", show_alert=True)
        return

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    buttons = [
        [InlineKeyboardButton(
            text=f"☠️ {lord.full_name} ({lord.house.name if lord.house else 'xonadonsiz'})",
            callback_data=f"admin:kill_lord_confirm:{lord.id}"
        )]
        for lord in lords
    ]
    buttons.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin:back")])

    await callback.message.edit_text(
        "☠️ <b>Qaysi lordni o'ldirish?</b>\n\nTanlangan lord o'ldiriladi va barcha foydalanuvchilarga xabar yuboriladi.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:kill_lord_confirm:"))
async def admin_kill_lord_execute(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    lord_id = int(callback.data.split(":")[2])

    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)

        lord = await user_repo.get_by_id(lord_id)
        if not lord or lord.role != RoleEnum.LORD:
            await callback.answer("❌ Lord topilmadi.", show_alert=True)
            return

        house = await house_repo.get_by_id(lord.house_id) if lord.house_id else None
        lord_name = lord.full_name
        house_name = house.name if house else "Noma'lum xonadon"

        # Lordni o'ldirish: rolini MEMBER ga tushirish, xonadondan chiqarish
        lord.role = RoleEnum.MEMBER
        lord.house_id = None
        lord.region = None
        if house:
            house.lord_id = None

        # Xronikaga yozish
        from database.models import Chronicle
        chronicle_text = (
            f"☠️ <b>LORD O'LDIRILDI!</b>\n\n"
            f"👑 <b>{lord_name}</b> — <b>{house_name}</b> xonadonining lordi\n"
            f"admin tomonidan o'ldirildi.\n\n"
            f"🏰 <b>{house_name}</b> xonadoni lordsiz qoldi.\n"
            f"⚠️ Bu ibratli jazo hamma uchun esda qolsin!"
        )
        chronicle = Chronicle(event_type="lord_killed", description=chronicle_text)
        session.add(chronicle)
        await session.commit()

        # Barcha foydalanuvchilarni olish
        result = await session.execute(select(User).where(User.is_active == True))
        all_users = result.scalars().all()
        all_user_ids = [u.id for u in all_users]

    # Kanalga (xronikaga) yuborish
    from utils.chronicle import post_to_chronicle
    await post_to_chronicle(callback.bot, chronicle_text)

    # Barcha foydalanuvchilarga birin-ketin xabar yuborish (sleep bo'lmasin)
    user_msg = (
        f"☠️ <b>LORD O'LDIRILDI!</b>\n\n"
        f"👑 <b>{lord_name}</b> — <b>{house_name}</b> xonadonining lordi\n"
        f"admin tomonidan o'ldirildi.\n\n"
        f"⚠️ Bu ibratli jazo hamma uchun esda qolsin!"
    )

    sent = 0
    failed = 0
    for uid in all_user_ids:
        try:
            await callback.bot.send_message(uid, user_msg, parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1

    await callback.message.edit_text(
        f"✅ <b>{lord_name}</b> o'ldirildi!\n\n"
        f"📢 Xabar yuborildi: {sent} ta\n"
        f"❌ Yuborilmadi: {failed} ta\n"
        f"📜 Xronikaga yozildi.",
        parse_mode="HTML"
    )
    await callback.answer()


# ─── Admin: Omonat Sozlamalari ─────────────────────────────────────────────────
class DepositAdminState(StatesGroup):
    waiting_rate = State()
    waiting_duration = State()
    waiting_time = State()


@router.callback_query(F.data == "admin:deposit_settings")
async def admin_deposit_settings(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return
    async with AsyncSessionFactory() as session:
        cfg = BotSettingsRepo(session)
        rate = await cfg.get_float("deposit_rate_per_day")
        duration = await cfg.get_int("deposit_duration_days")
        dep_hour = await cfg.get_int("deposit_job_hour")
        dep_minute = await cfg.get_int("deposit_job_minute")

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📈 Kunlik foizni o'zgartirish", callback_data="admin:deposit_set_rate")],
        [InlineKeyboardButton(text="📅 Muddatni o'zgartirish", callback_data="admin:deposit_set_duration")],
        [InlineKeyboardButton(text="🕐 Foiz tushadigan vaqtni o'zgartirish", callback_data="admin:deposit_set_time")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin:back")],
    ])
    await callback.answer()
    await callback.message.edit_text(
        f"🏦 <b>Omonat Sozlamalari</b>\n\n"
        f"📈 Kunlik foiz: <b>{rate*100:.2f}%</b>\n"
        f"📅 Muddat: <b>{duration} kun</b>\n"
        f"💹 Jami foiz: <b>{rate*100*duration:.1f}%</b>\n"
        f"🕐 Foiz tushadigan vaqt: <b>{dep_hour:02d}:{dep_minute:02d}</b> (Toshkent)",
        reply_markup=kb,
        parse_mode="HTML"
    )


@router.callback_query(F.data == "admin:deposit_set_rate")
async def admin_deposit_set_rate_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(DepositAdminState.waiting_rate)
    await callback.answer()
    await callback.message.answer(
        "📈 Yangi <b>kunlik foiz</b> kiriting (masalan: 2 → 2% kunlik):",
        parse_mode="HTML"
    )


@router.message(DepositAdminState.waiting_rate)
async def admin_deposit_set_rate(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        val = float(message.text.strip().replace(",", "."))
        if val < 0 or val > 100:
            raise ValueError
    except ValueError:
        await message.answer("❌ 0 dan 100 gacha raqam kiriting:")
        return
    async with AsyncSessionFactory() as session:
        cfg = BotSettingsRepo(session)
        await cfg.set("deposit_rate_per_day", str(val / 100))
    await state.clear()
    await message.answer(f"✅ Kunlik foiz: <b>{val:.2f}%</b> qilib belgilandi.", parse_mode="HTML")


@router.callback_query(F.data == "admin:deposit_set_duration")
async def admin_deposit_set_duration_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(DepositAdminState.waiting_duration)
    await callback.answer()
    await callback.message.answer(
        "📅 Omonat muddatini <b>kun</b> bilan kiriting (masalan: 7):",
        parse_mode="HTML"
    )


@router.message(DepositAdminState.waiting_duration)
async def admin_deposit_set_duration(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        val = int(message.text.strip())
        if val < 1:
            raise ValueError
    except ValueError:
        await message.answer("❌ Kamida 1 kun kiriting:")
        return
    async with AsyncSessionFactory() as session:
        cfg = BotSettingsRepo(session)
        await cfg.set("deposit_duration_days", str(val))
    await state.clear()
    await message.answer(f"✅ Omonat muddati: <b>{val} kun</b> qilib belgilandi.", parse_mode="HTML")


@router.callback_query(F.data == "admin:deposit_set_time")
async def admin_deposit_set_time_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(DepositAdminState.waiting_time)
    await callback.answer()
    await callback.message.answer(
        "🕐 Foiz tushadigan <b>vaqtni</b> kiriting.\n\n"
        "Format: <code>HH:MM</code> (24 soatlik, Toshkent vaqti)\n"
        "Masalan: <code>01:00</code> yoki <code>08:30</code>",
        parse_mode="HTML"
    )


@router.message(DepositAdminState.waiting_time)
async def admin_deposit_set_time(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    text = message.text.strip()
    try:
        parts = text.split(":")
        if len(parts) != 2:
            raise ValueError
        hour = int(parts[0])
        minute = int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except ValueError:
        await message.answer("❌ Noto'g'ri format. HH:MM shaklida kiriting (masalan: 01:00):")
        return

    async with AsyncSessionFactory() as session:
        cfg = BotSettingsRepo(session)
        await cfg.set("deposit_job_hour", str(hour))
        await cfg.set("deposit_job_minute", str(minute))

    await state.clear()

    from utils.scheduler import reload_deposit_job
    await reload_deposit_job(hour, minute)

    await message.answer(
        f"✅ Foiz tushadigan vaqt: <b>{hour:02d}:{minute:02d}</b> (Toshkent) qilib belgilandi.\n"
        f"Scheduler qayta yuklandi!",
        parse_mode="HTML"
    )


# ─── RITSAR SOZLAMALARI ──────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:knight_settings")
async def admin_knight_settings(callback: CallbackQuery):
    from config.settings import settings as s
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗡️ Maks askar limitini o'zgartirish", callback_data="admin:knight:max_soldiers")],
        [InlineKeyboardButton(text="🌾 Kunlik farm miqdorini o'zgartirish", callback_data="admin:knight:daily_farm")],
        [InlineKeyboardButton(text="🛒 Bir marta xarid limitini o'zgartirish", callback_data="admin:knight:buy_limit")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin:back")],
    ])
    await callback.answer()
    await callback.message.edit_text(
        f"⚔️ <b>RITSAR SOZLAMALARI</b>\n\n"
        f"🗡️ Maks askar: <b>{s.KNIGHT_MAX_SOLDIERS}</b>\n"
        f"🌾 Kunlik farm: <b>{s.KNIGHT_DAILY_FARM}</b> askar\n"
        f"🛒 Xarid limiti: <b>{s.KNIGHT_SOLDIER_BUY_LIMIT}</b> ta\n\n"
        f"O'zgartirmoqchi bo'lgan sozlamani tanlang:",
        reply_markup=kb,
        parse_mode="HTML"
    )


@router.callback_query(F.data == "admin:knight:max_soldiers")
async def admin_knight_max_soldiers(callback: CallbackQuery, state: FSMContext):
    from config.settings import settings as s
    await state.set_state(AdminState.waiting_knight_max_soldiers)
    await callback.answer()
    await callback.message.answer(
        f"🗡️ <b>Ritsarning maksimal askar soni</b>\n\n"
        f"Hozirgi qiymat: <b>{s.KNIGHT_MAX_SOLDIERS}</b>\n\n"
        f"Yangi qiymatni kiriting (butun son):",
        parse_mode="HTML"
    )


@router.message(AdminState.waiting_knight_max_soldiers)
async def admin_knight_max_soldiers_input(message: Message, state: FSMContext):
    try:
        val = int(message.text.strip())
        if val <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Musbat butun son kiriting.")
        return

    from database.engine import AsyncSessionFactory
    from database.repositories import BotSettingsRepo
    async with AsyncSessionFactory() as session:
        cfg = BotSettingsRepo(session)
        await cfg.set("knight_max_soldiers", str(val))

    # Runtime o'zgartirish
    from config.settings import settings as s
    s.KNIGHT_MAX_SOLDIERS = val

    await state.clear()
    await message.answer(
        f"✅ Ritsarning maks askar soni: <b>{val}</b> qilib belgilandi.",
        parse_mode="HTML"
    )


@router.callback_query(F.data == "admin:knight:daily_farm")
async def admin_knight_daily_farm(callback: CallbackQuery, state: FSMContext):
    from config.settings import settings as s
    await state.set_state(AdminState.waiting_knight_daily_farm)
    await callback.answer()
    await callback.message.answer(
        f"🌾 <b>Ritsarning kunlik farm miqdori</b>\n\n"
        f"Hozirgi qiymat: <b>{s.KNIGHT_DAILY_FARM}</b> askar\n\n"
        f"Yangi qiymatni kiriting (butun son):",
        parse_mode="HTML"
    )


@router.message(AdminState.waiting_knight_daily_farm)
async def admin_knight_daily_farm_input(message: Message, state: FSMContext):
    try:
        val = int(message.text.strip())
        if val <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Musbat butun son kiriting.")
        return

    from database.engine import AsyncSessionFactory
    from database.repositories import BotSettingsRepo
    async with AsyncSessionFactory() as session:
        cfg = BotSettingsRepo(session)
        await cfg.set("knight_daily_farm", str(val))

    from config.settings import settings as s
    s.KNIGHT_DAILY_FARM = val

    await state.clear()
    await message.answer(
        f"✅ Ritsarning kunlik farm: <b>{val}</b> askar qilib belgilandi.",
        parse_mode="HTML"
    )


@router.callback_query(F.data == "admin:knight:buy_limit")
async def admin_knight_buy_limit(callback: CallbackQuery, state: FSMContext):
    from config.settings import settings as s
    await state.set_state(AdminState.waiting_knight_buy_limit)
    await callback.answer()
    await callback.message.answer(
        f"🛒 <b>Ritsarning bir marta xarid limiti</b>\n\n"
        f"Hozirgi qiymat: <b>{s.KNIGHT_SOLDIER_BUY_LIMIT}</b> ta\n\n"
        f"Yangi qiymatni kiriting (butun son):",
        parse_mode="HTML"
    )


@router.message(AdminState.waiting_knight_buy_limit)
async def admin_knight_buy_limit_input(message: Message, state: FSMContext):
    try:
        val = int(message.text.strip())
        if val <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Musbat butun son kiriting.")
        return

    from database.engine import AsyncSessionFactory
    from database.repositories import BotSettingsRepo
    async with AsyncSessionFactory() as session:
        cfg = BotSettingsRepo(session)
        await cfg.set("knight_soldier_buy_limit", str(val))

    from config.settings import settings as s
    s.KNIGHT_SOLDIER_BUY_LIMIT = val

    await state.clear()
    await message.answer(
        f"✅ Ritsarning xarid limiti: <b>{val}</b> ta qilib belgilandi.",
        parse_mode="HTML"
    )


# ─────────────────────────────────────────────────
# BOSQICH 3 — O'YIN PAUZA BOSHQARUVI
# ─────────────────────────────────────────────────

@router.callback_query(F.data == "admin:toggle_pause")
async def admin_toggle_pause(callback: CallbackQuery, state: FSMContext):
    """O'yinni pauza / davom ettirish"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    async with AsyncSessionFactory() as session:
        cfg = BotSettingsRepo(session)
        current = await cfg.get("game_paused") or "false"

        if current.strip().lower() == "true":
            # Pauzani ochish
            await cfg.set("game_paused", "false")
            await cfg.set("pause_reason", "")
            await session.commit()
            await callback.answer("▶️ O'yin davom ettirildi.", show_alert=True)
            await callback.message.edit_text(
                "▶️ <b>O'yin qayta ishga tushirildi.</b>\n\n"
                "Foydalanuvchilar endi botdan foydalana oladi.",
                parse_mode="HTML",
                reply_markup=admin_keyboard()
            )
        else:
            # Pauza sababi so'rash
            await state.set_state(AdminState.waiting_pause_reason)
            await callback.answer()
            await callback.message.answer(
                "⏸ <b>O'yinni to'xtatish</b>\n\n"
                "Pauza sababini yozing — foydalanuvchilarga ko'rsatiladi.\n"
                "(Masalan: <i>Texnik yangilanish olib borilmoqda</i>)",
                parse_mode="HTML"
            )


@router.message(AdminState.waiting_pause_reason)
async def admin_pause_reason_input(message: Message, state: FSMContext):
    """Pauza sababini qabul qilish va o'yinni to'xtatish"""
    if not is_admin(message.from_user.id):
        return

    reason = message.text.strip()
    if not reason:
        await message.answer("❌ Sabab bo'sh bo'lishi mumkin emas.")
        return

    async with AsyncSessionFactory() as session:
        cfg = BotSettingsRepo(session)
        await cfg.set("game_paused", "true")
        await cfg.set("pause_reason", reason)
        await session.commit()

    await state.clear()
    await message.answer(
        f"⏸ <b>O'yin to'xtatildi!</b>\n\n"
        f"📌 Sabab: <i>{reason}</i>\n\n"
        f"Foydalanuvchilar bu xabarni ko'radi.\n"
        f"Qayta yoqish uchun: Admin Panel → ⏸ O'yinni Pauza/Davom",
        parse_mode="HTML"
    )


# ─────────────────────────────────────────────────
# BOSQICH 4 — XONADON RESURSLARI TAHRIRLASH
# ─────────────────────────────────────────────────

_HRES_FIELDS = {
    "market":   ("market_buy_limit",  "🛒 Bozor kunlik askar limiti"),
    "bank_min": ("bank_min_loan",     "🏦 Bank minimum qarz"),
    "bank_max": ("bank_max_loan",     "🏦 Bank maksimum qarz"),
    "farm":     ("daily_farm_amount", "🌾 Kunlik farm miqdori (askar)"),
}


def _hres_keyboard(house_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Bozor limiti",  callback_data=f"admin:hres:edit:market:{house_id}")],
        [InlineKeyboardButton(text="🏦 Bank min",      callback_data=f"admin:hres:edit:bank_min:{house_id}")],
        [InlineKeyboardButton(text="🏦 Bank max",      callback_data=f"admin:hres:edit:bank_max:{house_id}")],
        [InlineKeyboardButton(text="🌾 Kunlik farm",   callback_data=f"admin:hres:edit:farm:{house_id}")],
        [InlineKeyboardButton(text="🔙 Orqaga",        callback_data="admin:house_resources")],
    ])


@router.callback_query(F.data == "admin:house_resources")
async def admin_house_resources_menu(callback: CallbackQuery):
    """Barcha xonadonlar ro'yxati — resurs tahrirlash uchun"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    async with AsyncSessionFactory() as session:
        house_repo = HouseRepo(session)
        houses = await house_repo.get_all()

    kb = house_list_keyboard(houses, action_prefix="admin:hres", back_to="admin:back")
    await callback.answer()
    await callback.message.edit_text(
        "🏰 <b>Xonadon Resurslari</b>\n\n"
        "Tahrirlash uchun xonadon tanlang:",
        reply_markup=kb,
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("admin:hres:") & ~F.data.startswith("admin:hres:edit:"))
async def admin_house_resources_select(callback: CallbackQuery):
    """Tanlangan xonadonning joriy resurs sozlamalarini ko'rsatadi"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    house_id = int(callback.data.split(":")[2])

    async with AsyncSessionFactory() as session:
        house_repo = HouseRepo(session)
        res_repo   = HouseResourcesRepo(session)

        house = await house_repo.get_by_id(house_id)
        if not house:
            await callback.answer("❌ Xonadon topilmadi.", show_alert=True)
            return

        res = await res_repo.get_or_create(house_id)
        await session.commit()

    text = (
        f"🏰 <b>{house.name}</b> — Resurs sozlamalari\n\n"
        f"🛒 Bozor kunlik askar limiti: <b>{res.market_buy_limit}</b>\n"
        f"🏦 Bank min qarz: <b>{res.bank_min_loan:,}</b>\n"
        f"🏦 Bank max qarz: <b>{res.bank_max_loan:,}</b>\n"
        f"🌾 Kunlik farm (askar): <b>{res.daily_farm_amount}</b>\n"
    )
    await callback.answer()
    await callback.message.edit_text(
        text,
        reply_markup=_hres_keyboard(house_id),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("admin:hres:edit:"))
async def admin_house_resources_edit_start(callback: CallbackQuery, state: FSMContext):
    """Tahrirlash maydonini tanlash — qiymat kiritish bosqichi"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    # admin:hres:edit:field:house_id
    parts    = callback.data.split(":")
    field    = parts[3]
    house_id = int(parts[4])

    if field not in _HRES_FIELDS:
        await callback.answer("❌ Noma'lum maydon.", show_alert=True)
        return

    _, label = _HRES_FIELDS[field]

    await state.update_data(hres_house_id=house_id, hres_field=field)
    await state.set_state(AdminState.waiting_house_resource_value)
    await callback.answer()
    await callback.message.answer(
        f"✏️ <b>{label}</b>\n\n"
        f"Yangi qiymatni kiriting (musbat son):",
        parse_mode="HTML"
    )


@router.message(AdminState.waiting_house_resource_value)
async def admin_house_resources_save(message: Message, state: FSMContext):
    """Yangi qiymatni qabul qilib DB ga yozadi"""
    if not is_admin(message.from_user.id):
        return

    try:
        val = int(message.text.strip())
        if val <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("❌ Musbat butun son kiriting.")
        return

    data     = await state.get_data()
    house_id = data.get("hres_house_id")
    field    = data.get("hres_field")

    if not house_id or not field or field not in _HRES_FIELDS:
        await message.answer("❌ Xatolik yuz berdi. Qaytadan urinib ko'ring.")
        await state.clear()
        return

    db_field, label = _HRES_FIELDS[field]

    async with AsyncSessionFactory() as session:
        house_repo = HouseRepo(session)
        res_repo   = HouseResourcesRepo(session)

        house = await house_repo.get_by_id(house_id)
        await res_repo.update(house_id, **{db_field: val})
        await session.commit()

    await state.clear()
    await message.answer(
        f"✅ <b>{house.name if house else house_id}</b>\n"
        f"{label}: <b>{val:,}</b> ga o'rnatildi.",
        parse_mode="HTML"
    )
