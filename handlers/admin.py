from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from database.engine import AsyncSessionFactory
from database.repositories import UserRepo, HouseRepo, MarketRepo, BotSettingsRepo
from database.models import RoleEnum, RegionEnum, House
from keyboards import admin_keyboard, back_only_keyboard
from config.settings import settings
from sqlalchemy import select, update, delete, text
from database.models import User, MarketPrice, IronBankLoan, Alliance, War, Chronicle, InternalMessage

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
            )
        )
        await session.flush()
        # 2. Bog'liq jadvallarni tozalash
        await session.execute(delete(IronBankLoan))
        await session.execute(delete(InternalMessage))
        await session.execute(delete(Chronicle))
        await session.execute(delete(Alliance))
        await session.execute(delete(War))
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
