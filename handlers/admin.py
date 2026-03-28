from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from database.engine import AsyncSessionFactory
from database.repositories import UserRepo, HouseRepo, MarketRepo
from database.models import RoleEnum
from keyboards import admin_keyboard
from config.settings import settings
from sqlalchemy import select, update
from database.models import User, MarketPrice

router = Router()

# Admin ID lar — .env dan to'ldiring
ADMIN_IDS: list[int] = []


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


class AdminState(StatesGroup):
    waiting_price_item = State()
    waiting_price_value = State()
    waiting_interest = State()
    waiting_broadcast = State()
    waiting_give_gold_user = State()
    waiting_give_gold_amount = State()


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

    # Runtime da o'zgartirish (yoki DB ga saqlash mumkin)
    import handlers.bank as bank_module
    bank_module.CURRENT_INTEREST_RATE = rate / 100
    settings.DEFAULT_INTEREST_RATE = rate / 100

    await message.answer(f"✅ Foiz stavkasi {rate:.0f}% ga o'zgartirildi!")
    await state.clear()


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


@router.message(Command("give_gold"))
async def admin_give_gold(message: Message, state: FSMContext):
    """Admin buyrug'i: /give_gold <user_id> <amount>"""
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
        await message.bot.send_message(
            target_id,
            f"🎁 Admindan {amount} oltin sovg'a qilindi!",
        )
    except Exception:
        pass
