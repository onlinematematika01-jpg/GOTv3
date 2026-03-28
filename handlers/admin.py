from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from database.engine import AsyncSessionFactory
from database.repositories import UserRepo, HouseRepo, MarketRepo
from database.models import RoleEnum, RegionEnum, House
from keyboards import admin_keyboard
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

    await state.set_state(AdminState.waiting_interest)
    await callback.answer()
    await callback.message.answer(
        f"🏦 Joriy foiz: {settings.DEFAULT_INTEREST_RATE * 100:.0f}%\n"
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

    import handlers.bank as bank_module
    bank_module.CURRENT_INTEREST_RATE = rate / 100
    settings.DEFAULT_INTEREST_RATE = rate / 100

    await message.answer(f"✅ Foiz stavkasi {rate:.0f}% ga o'zgartirildi!")
    await state.clear()


# ─── BANK LIMIT (MIN / MAX) ─────────────────────────────────────────────────
@router.callback_query(F.data == "admin:bank_limits")
async def admin_bank_limits(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
        return

    import handlers.admin as self_module
    await state.set_state(AdminState.waiting_bank_min)
    await callback.answer()
    await callback.message.answer(
        f"🏦 <b>Bank qarz limiti sozlash</b>\n\n"
        f"Joriy minimal qarz: {BANK_MIN_LOAN:,} tanga\n"
        f"Joriy maksimal qarz: {BANK_MAX_LOAN:,} tanga\n\n"
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

    import handlers.bank as bank_module
    global BANK_MIN_LOAN
    BANK_MIN_LOAN = val
    bank_module.BANK_MIN_LOAN = val

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

    import handlers.bank as bank_module
    global BANK_MAX_LOAN
    BANK_MAX_LOAN = val
    bank_module.BANK_MAX_LOAN = val

    await message.answer(
        f"✅ <b>Bank limiti yangilandi!</b>\n\n"
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
    await callback.message.answer(text, parse_mode="HTML")


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

    # Bo'sh (xonadonsiz) regionlarni topamiz
    async with AsyncSessionFactory() as session:
        result = await session.execute(select(House.region))
        used_regions = {r for r, in result.all()}

    free = {k: v for k, v in REGION_NAMES.items() if REGION_LIST[k] not in used_regions}

    if not free:
        await callback.answer("❌ Barcha xududlarda xonadon mavjud!", show_alert=True)
        return

    region_text = "\n".join([f"{k}. {v}" for k, v in free.items()])
    await state.update_data(free_regions=list(free.keys()))
    await state.set_state(AdminState.waiting_house_region)
    await callback.answer()
    await callback.message.answer(
        f"🏰 <b>Yangi xonadon qo'shish</b>\n\n"
        f"Bo'sh xududlar:\n{region_text}\n\n"
        f"Xududning raqamini kiriting:",
        parse_mode="HTML"
    )


@router.message(AdminState.waiting_house_region)
async def admin_add_house_region(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    choice = message.text.strip()

    if choice not in data.get("free_regions", []):
        await message.answer("❌ Noto'g'ri raqam. Ro'yxatdan tanlang.")
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
        # Bog'liq jadvallarni tartib bilan tozalash
        await session.execute(delete(IronBankLoan))
        await session.execute(delete(InternalMessage))
        await session.execute(delete(Chronicle))
        await session.execute(delete(Alliance))
        await session.execute(delete(War))
        # Foydalanuvchilarni tozalash
        await session.execute(delete(User))
        # Xonadonlarni reset qilish (o'chirmasdan)
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
