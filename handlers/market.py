from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database.engine import AsyncSessionFactory
from database.repositories import UserRepo, HouseRepo, MarketRepo, CustomItemRepo
from keyboards import market_keyboard, quantity_keyboard, back_only_keyboard
from keyboards.keyboards import custom_item_market_keyboard
from sqlalchemy import update
from database.models import User, House, RoleEnum

router = Router()


class MarketState(StatesGroup):
    waiting_quantity = State()
    waiting_custom_quantity = State()


ITEM_NAMES = {
    "soldier": "🗡️ Askar",
    "dragon": "🐉 Ajdar",
    "scorpion": "🏹 Skorpion",
}


async def _build_market_text(user_id: int):
    """Bozor matni va keyboard'ini qaytaradi (standart + custom itemlar)"""
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)
        market_repo = MarketRepo(session)
        custom_repo = CustomItemRepo(session)

        user = await user_repo.get_by_id(user_id)
        prices = await market_repo.get_all_prices()
        custom_items = await custom_repo.get_all_active()

        treasury = 0
        if user and user.house_id:
            house = await house_repo.get_by_id(user.house_id)
            treasury = house.treasury if house else 0

    lines = [
        "🛒 <b>BOZOR</b>\n",
        f"💰 Xonadon xazinasi: <b>{treasury:,}</b> tanga\n",
        "─── Standart qurollar ───",
        f"🗡️ Askar: <b>{prices.get('soldier', 1)}</b> tanga/dona",
        f"🐉 Ajdar: <b>{prices.get('dragon', 150)}</b> tanga/dona",
        f"🏹 Skorpion: <b>{prices.get('scorpion', 25)}</b> tanga/dona",
    ]

    if custom_items:
        lines.append("\n─── Maxsus qurollar ───")
        for item in custom_items:
            stock_text = ""
            if item.stock_remaining is not None:
                if item.stock_remaining == 0:
                    stock_text = " ❌ <i>Tugadi</i>"
                else:
                    stock_text = f" (qoldi: <b>{item.stock_remaining}</b>)"
            lines.append(f"{item.emoji} {item.name}: <b>{item.price:,}</b> tanga/dona{stock_text}")

    lines.append("\n📌 Nima sotib olmoqchisiz?")
    lines.append("⚠️ Faqat xonadon lordi xazinadan xarid qila oladi.")

    return "\n".join(lines), custom_items


@router.message(F.text == "🛒 Bozor")
async def show_market(message: Message):
    text, custom_items = await _build_market_text(message.from_user.id)
    await message.answer(
        text,
        reply_markup=market_keyboard(custom_items),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "market:back")
async def market_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    text, custom_items = await _build_market_text(callback.from_user.id)
    await callback.answer()
    await callback.message.edit_text(
        text,
        reply_markup=market_keyboard(custom_items),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "market:prices")
async def show_prices(callback: CallbackQuery):
    async with AsyncSessionFactory() as session:
        market_repo = MarketRepo(session)
        custom_repo = CustomItemRepo(session)
        prices = await market_repo.get_all_prices()
        custom_items = await custom_repo.get_all_active()

    lines = [
        "📊 <b>Joriy Bozor Narxlari:</b>\n",
        "─── Standart ───",
        f"🗡️ Askar: {prices.get('soldier', 1)} tanga",
        f"🐉 Ajdar: {prices.get('dragon', 150)} tanga",
        f"🏹 Skorpion: {prices.get('scorpion', 25)} tanga",
    ]
    if custom_items:
        lines.append("\n─── Maxsus ───")
        for item in custom_items:
            stock_text = ""
            if item.stock_remaining is not None:
                stock_text = f" | qoldi: {item.stock_remaining}" if item.stock_remaining > 0 else " | ❌ Tugadi"
            lines.append(f"{item.emoji} {item.name}: {item.price:,} tanga{stock_text}")

    await callback.answer()
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=back_only_keyboard("market:back"),
        parse_mode="HTML"
    )


# ── Standart itemlar sotib olish ──────────────────────────────────────────

@router.callback_query(F.data.startswith("market:buy:"))
async def select_quantity(callback: CallbackQuery, state: FSMContext):
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)
        if not user or user.role not in [RoleEnum.LORD, RoleEnum.HIGH_LORD, RoleEnum.ADMIN]:
            await callback.answer("❌ Faqat xonadon lordi xarid qila oladi.", show_alert=True)
            return

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


async def _do_purchase(message, user_id: int, item: str, qty: int, state: FSMContext):
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)
        market_repo = MarketRepo(session)

        user = await user_repo.get_by_id(user_id)
        if not user or not user.house_id:
            await message.answer("❌ Xonadoningiz yo'q.")
            await state.clear()
            return

        house = await house_repo.get_by_id(user.house_id)
        if not house:
            await message.answer("❌ Xonadon topilmadi.")
            await state.clear()
            return

        price = await market_repo.get_price(item)
        total_cost = price * qty

        if house.treasury < total_cost:
            await message.answer(
                f"❌ Xonadon xazinasida yetarli oltin yo'q!\n"
                f"Kerak: {total_cost:,} | Xazina: {house.treasury:,}",
                reply_markup=back_only_keyboard("market:back")
            )
            await state.clear()
            return

        await house_repo.update_treasury(user.house_id, -total_cost)

        field_map = {
            "soldier":  ("soldiers",  "total_soldiers"),
            "dragon":   ("dragons",   "total_dragons"),
            "scorpion": ("scorpions", "total_scorpions"),
        }
        user_field, house_field = field_map[item]

        await session.execute(
            update(User).where(User.id == user_id).values(
                **{user_field: getattr(User, user_field) + qty}
            )
        )
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
            f"💰 Xazinadan sarflandi: {total_cost:,} tanga\n"
            f"💰 Xazina qoldig'i: {house.treasury - total_cost:,} tanga",
            reply_markup=back_only_keyboard("market:back"),
            parse_mode="HTML"
        )

        # Kanalga xabar
        from utils.chronicle import post_to_chronicle
        try:
            await post_to_chronicle(
                message.bot,
                f"🛒 <b>BOZOR XABARI</b>\n\n"
                f"🏰 <b>{house.name}</b> xonadoni\n"
                f"{item_label}: +{qty} ta sotib oldi\n"
                f"💰 Sarflandi: {total_cost:,} tanga"
            )
        except Exception:
            pass
    await state.clear()


# ── Maxsus itemlar sotib olish ────────────────────────────────────────────

@router.callback_query(F.data.startswith("market:custom:"))
async def select_custom_quantity(callback: CallbackQuery, state: FSMContext):
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)
        if not user or user.role not in [RoleEnum.LORD, RoleEnum.HIGH_LORD, RoleEnum.ADMIN]:
            await callback.answer("❌ Faqat xonadon lordi xarid qila oladi.", show_alert=True)
            return

    item_id = int(callback.data.split(":")[2])
    await state.update_data(custom_item_id=item_id)
    await state.set_state(MarketState.waiting_custom_quantity)

    await callback.answer()
    await callback.message.answer(
        "🔢 Nechta sotib olmoqchisiz? Raqam yozing:",
        reply_markup=quantity_keyboard(f"custom_{item_id}"),
    )


@router.callback_query(MarketState.waiting_custom_quantity, F.data.startswith("qty:"))
async def process_custom_item_qty_btn(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    qty_str = parts[2]
    if qty_str == "custom":
        await callback.answer()
        await callback.message.answer("✏️ Miqdorni yozing (raqam):")
        return
    qty = int(qty_str)
    data = await state.get_data()
    await _do_custom_purchase(callback.message, callback.from_user.id, data["custom_item_id"], qty, state)
    await callback.answer()


@router.message(MarketState.waiting_custom_quantity)
async def process_custom_item_qty_text(message: Message, state: FSMContext):
    try:
        qty = int(message.text.strip())
        if qty <= 0:
            raise ValueError
    except (ValueError, TypeError):
        await message.answer("❌ Musbat raqam kiriting.")
        return
    data = await state.get_data()
    await _do_custom_purchase(message, message.from_user.id, data["custom_item_id"], qty, state)


async def _do_custom_purchase(message, user_id: int, item_id: int, qty: int, state: FSMContext):
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)
        custom_repo = CustomItemRepo(session)

        user = await user_repo.get_by_id(user_id)
        if not user or not user.house_id:
            await message.answer("❌ Xonadoningiz yo'q.")
            await state.clear()
            return

        house = await house_repo.get_by_id(user.house_id)
        item = await custom_repo.get_by_id(item_id)

        if not item or not item.is_active:
            await message.answer("❌ Item topilmadi yoki sotuvda yo'q.")
            await state.clear()
            return

        # Stok cheklovini tekshirish
        if item.stock_remaining is not None:
            if item.stock_remaining == 0:
                await message.answer(
                    f"❌ <b>{item.emoji} {item.name}</b> tugab ketdi! Stokda qolmadi.",
                    reply_markup=back_only_keyboard("market:back"),
                    parse_mode="HTML"
                )
                await state.clear()
                return
            if item.stock_remaining < qty:
                await message.answer(
                    f"❌ Yetarli miqdor yo'q!\n"
                    f"So'raldigan: <b>{qty}</b> | Stokda qolgan: <b>{item.stock_remaining}</b>",
                    reply_markup=back_only_keyboard("market:back"),
                    parse_mode="HTML"
                )
                await state.clear()
                return

        total_cost = item.price * qty
        if house.treasury < total_cost:
            await message.answer(
                f"❌ Yetarli oltin yo'q!\n"
                f"Kerak: {total_cost:,} | Xazina: {house.treasury:,}",
                reply_markup=back_only_keyboard("market:back")
            )
            await state.clear()
            return

        await house_repo.update_treasury(user.house_id, -total_cost)

        # Stokni kamaytirish
        await custom_repo.reduce_stock(item_id, qty)

        await custom_repo.add_user_item(user_id, item_id, qty)
        await custom_repo.add_house_item(user.house_id, item_id, qty)

        # Qolgan stok
        stock_info = ""
        if item.stock_remaining is not None:
            remaining = item.stock_remaining - qty
            stock_info = f"\n📦 Stokda qoldi: <b>{remaining}</b> ta"

        await message.answer(
            f"✅ <b>Muvaffaqiyatli sotib olindi!</b>\n\n"
            f"{item.emoji} {item.name}: +{qty} ta\n"
            f"💰 Sarflandi: {total_cost:,} tanga\n"
            f"💰 Xazina qoldig'i: {house.treasury - total_cost:,} tanga"
            + stock_info,
            reply_markup=back_only_keyboard("market:back"),
            parse_mode="HTML"
        )

        # Kanalga xabar
        from utils.chronicle import post_to_chronicle
        try:
            await post_to_chronicle(
                message.bot,
                f"🛒 <b>BOZOR XABARI</b>\n\n"
                f"🏰 <b>{house.name}</b> xonadoni\n"
                f"{item.emoji} {item.name}: +{qty} ta sotib oldi\n"
                f"💰 Sarflandi: {total_cost:,} tanga"
                + (f"\n📦 Stokda qoldi: {item.stock_remaining - qty} ta" if item.stock_remaining is not None else "")
            )
        except Exception:
            pass
    await state.clear()
