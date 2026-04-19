"""
Ritsar bozori — faqat askar sotib olish
Limit: KNIGHT_SOLDIER_BUY_LIMIT (admin belgilaydi)
"""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database.engine import AsyncSessionFactory
from database.repositories import UserRepo, MarketRepo
from database.models import RoleEnum
from config.settings import settings

router = Router()


class KnightMarketFSM(StatesGroup):
    waiting_quantity = State()


@router.message(F.text == "🛒 Ritsar Bozori")
async def knight_market_show(message: Message):
    async with AsyncSessionFactory() as session:
        user_repo   = UserRepo(session)
        market_repo = MarketRepo(session)
        from database.repositories import KnightRepo
        knight_repo = KnightRepo(session)

        user = await user_repo.get_by_id(message.from_user.id)
        if not user or user.role != RoleEnum.KNIGHT:
            await message.answer("❌ Bu bozor faqat ritsarlar uchun.")
            return

        profile = await knight_repo.get_profile(message.from_user.id)
        if not profile or not profile.is_active:
            await message.answer("❌ Ritsar profilingiz topilmadi.")
            return

        prices = await market_repo.get_all_prices()
        soldier_price = prices.get("soldier", settings.SOLDIER_PRICE)

        available_slots = settings.KNIGHT_MAX_SOLDIERS - profile.soldiers
        max_buy = min(settings.KNIGHT_SOLDIER_BUY_LIMIT, available_slots)

        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        if max_buy > 0:
            builder.button(text="🗡️ Askar Sotib Olish", callback_data="kmarket:buy")
        builder.adjust(1)

        await message.answer(
            f"🛒 <b>RITSAR BOZORI</b>\n\n"
            f"🗡️ Askar narxi: <b>{soldier_price}</b> tanga/dona\n\n"
            f"📊 Sizning ahvolingiz:\n"
            f"  • Mavjud askarlar: <b>{profile.soldiers}</b>/{settings.KNIGHT_MAX_SOLDIERS}\n"
            f"  • Bir marta xarid limiti: <b>{settings.KNIGHT_SOLDIER_BUY_LIMIT}</b> ta\n"
            f"  • Hozir sotib olish mumkin: <b>{max_buy}</b> ta\n\n"
            f"⚠️ Xazinadan xonadon oltin sarflanadi.",
            reply_markup=builder.as_markup() if max_buy > 0 else None,
            parse_mode="HTML"
        )

        if max_buy <= 0:
            await message.answer(
                "❌ Askar limit to'liq yoki bir marta xarid limiti oshib ketdi.\n"
                "Askarlaringizni urushda ishlating!"
            )


@router.callback_query(F.data == "kmarket:buy")
async def knight_market_buy_start(callback: CallbackQuery, state: FSMContext):
    async with AsyncSessionFactory() as session:
        user_repo   = UserRepo(session)
        from database.repositories import KnightRepo
        knight_repo = KnightRepo(session)

        user    = await user_repo.get_by_id(callback.from_user.id)
        profile = await knight_repo.get_profile(callback.from_user.id)

        if not user or user.role != RoleEnum.KNIGHT or not profile:
            await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
            return

        available_slots = settings.KNIGHT_MAX_SOLDIERS - profile.soldiers
        max_buy = min(settings.KNIGHT_SOLDIER_BUY_LIMIT, available_slots)

        if max_buy <= 0:
            await callback.answer("❌ Xarid limiti to'liq.", show_alert=True)
            return

        await state.update_data(max_buy=max_buy)
        await state.set_state(KnightMarketFSM.waiting_quantity)
        await callback.answer()
        await callback.message.answer(
            f"🗡️ Nechta askar sotib olmoqchisiz?\n"
            f"Maksimal: <b>{max_buy}</b> ta",
            parse_mode="HTML"
        )


@router.message(KnightMarketFSM.waiting_quantity)
async def knight_market_buy_confirm(message: Message, state: FSMContext):
    data = await state.get_data()
    max_buy = data.get("max_buy", 0)

    try:
        qty = int(message.text.strip())
        if qty <= 0 or qty > max_buy:
            raise ValueError
    except (ValueError, TypeError):
        await message.answer(f"❌ 1 dan {max_buy} gacha son kiriting.")
        return

    async with AsyncSessionFactory() as session:
        user_repo   = UserRepo(session)
        house_repo  = HouseRepo(session)
        market_repo = MarketRepo(session)
        from database.repositories import KnightRepo, HouseRepo
        knight_repo = KnightRepo(session)
        house_repo  = HouseRepo(session)

        user    = await user_repo.get_by_id(message.from_user.id)
        profile = await knight_repo.get_profile(message.from_user.id)
        house   = await house_repo.get_by_id(user.house_id)
        prices  = await market_repo.get_all_prices()

        soldier_price = prices.get("soldier", settings.SOLDIER_PRICE)
        total_cost    = qty * soldier_price

        if house.treasury < total_cost:
            await message.answer(
                f"❌ Xonadon xazinasida yetarli oltin yo'q!\n"
                f"Kerak: {total_cost} | Mavjud: {house.treasury}"
            )
            await state.clear()
            return

        # Xazinadan ayirish
        from sqlalchemy import update
        from database.models import House
        await session.execute(
            update(House).where(House.id == user.house_id)
            .values(treasury=House.treasury - total_cost)
        )

        # Ritsar askarlariga qo'shish
        await knight_repo.add_soldiers(message.from_user.id, qty)
        await session.commit()

        await state.clear()
        await message.answer(
            f"✅ <b>Sotib olindi!</b>\n\n"
            f"🗡️ +{qty} askar\n"
            f"💰 -{total_cost} tanga\n"
            f"Jami askarlaringiz: <b>{profile.soldiers + qty}</b>/{settings.KNIGHT_MAX_SOLDIERS}",
            parse_mode="HTML"
        )
