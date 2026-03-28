from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database.engine import AsyncSessionFactory
from database.repositories import UserRepo, HouseRepo, MarketRepo
from keyboards import market_keyboard, quantity_keyboard
from sqlalchemy import update
from database.models import User, House

router = Router()


class MarketState(StatesGroup):
    waiting_quantity = State()


ITEM_NAMES = {
    "soldier": "🗡️ Askar",
    "dragon": "🐉 Ajdar",
    "scorpion": "🏹 Skorpion",
}


@router.message(F.text == "🛒 Bozor")
async def show_market(message: Message):
    async with AsyncSessionFactory() as session:
        market_repo = MarketRepo(session)
        prices = await market_repo.get_all_prices()

        text = (
            "🛒 <b>BOZOR</b>\n\n"
            f"🗡️ Askar: <b>{prices.get('soldier', 1)}</b> tanga/dona\n"
            f"🐉 Ajdar: <b>{prices.get('dragon', 150)}</b> tanga/dona\n"
            f"🏹 Skorpion: <b>{prices.get('scorpion', 25)}</b> tanga/dona\n\n"
            "📌 Nima sotib olmoqchisiz?"
        )
        await message.answer(text, reply_markup=market_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "market:prices")
async def show_prices(callback: CallbackQuery):
    async with AsyncSessionFactory() as session:
        market_repo = MarketRepo(session)
        prices = await market_repo.get_all_prices()

    text = (
        "📊 <b>Joriy Bozor Narxlari:</b>\n\n"
        f"🗡️ Askar: {prices.get('soldier', 1)} tanga\n"
        f"🐉 Ajdar: {prices.get('dragon', 150)} tanga\n"
        f"🏹 Skorpion: {prices.get('scorpion', 25)} tanga"
    )
    await callback.answer()
    await callback.message.answer(text, parse_mode="HTML")


@router.callback_query(F.data.startswith("market:buy:"))
async def select_quantity(callback: CallbackQuery, state: FSMContext):
    item = callback.data.split(":")[2]
    await state.update_data(item=item)
    await state.set_state(MarketState.waiting_quantity)

    await callback.answer()
    await callback.message.answer(
        f"{ITEM_NAMES.get(item, item)} — Nechta sotib olmoqchisiz?",
        reply_markup=quantity_keyboard(item),
    )


@router.callback_query(MarketState.waiting_quantity, F.data.startswith("qty:"))
async def process_quantity(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    item = parts[1]
    qty_str = parts[2]

    if qty_str == "custom":
        await callback.answer()
        await callback.message.answer("✏️ Miqdorni yozing (raqam):")
        return

    qty = int(qty_str)
    await _do_purchase(callback.message, callback.from_user.id, item, qty, state)
    await callback.answer()


@router.message(MarketState.waiting_quantity)
async def process_custom_quantity(message: Message, state: FSMContext):
    data = await state.get_data()
    item = data.get("item")

    try:
        qty = int(message.text.strip())
        if qty <= 0:
            raise ValueError
    except (ValueError, TypeError):
        await message.answer("❌ Noto'g'ri son. Iltimos, musbat raqam kiriting.")
        return

    await _do_purchase(message, message.from_user.id, item, qty, state)


async def _do_purchase(message: Message, user_id: int, item: str, qty: int, state: FSMContext):
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        market_repo = MarketRepo(session)
        house_repo = HouseRepo(session)

        user = await user_repo.get_by_id(user_id)
        if not user:
            await message.answer("❌ Foydalanuvchi topilmadi.")
            await state.clear()
            return

        price = await market_repo.get_price(item)
        total_cost = price * qty

        if user.gold < total_cost:
            await message.answer(
                f"❌ Yetarli oltin yo'q!\n"
                f"Kerak: {total_cost:,} | Sizda: {user.gold:,}"
            )
            await state.clear()
            return

        # Oltin ayirish
        await user_repo.update_gold(user_id, -total_cost)

        # Qurol qo'shish — foydalanuvchi va xonadon
        field_map = {
            "soldier": ("soldiers", "total_soldiers"),
            "dragon": ("dragons", "total_dragons"),
            "scorpion": ("scorpions", "total_scorpions"),
        }

        user_field, house_field = field_map[item]

        await session.execute(
            update(User).where(User.id == user_id).values(
                **{user_field: getattr(User, user_field) + qty}
            )
        )

        if user.house_id:
            await session.execute(
                update(House).where(House.id == user.house_id).values(
                    **{house_field: getattr(House, house_field) + qty}
                )
            )

        await session.commit()

        item_label = ITEM_NAMES.get(item, item)
        await message.answer(
            f"✅ <b>Muvaffaqiyatli sotib olindi!</b>\n\n"
            f"{item_label}: +{qty} ta\n"
            f"💰 Sarflandi: {total_cost:,} tanga\n"
            f"💰 Qoldi: {user.gold - total_cost:,} tanga",
            parse_mode="HTML"
        )

    await state.clear()
