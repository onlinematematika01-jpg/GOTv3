import html as _html
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database.engine import AsyncSessionFactory
from database.repositories import UserRepo, HouseRepo, MarketRepo, CustomItemRepo, HouseResourcesRepo, DailyPurchaseRepo, PreAssignedLordRepo, BotSettingsRepo
from keyboards import market_keyboard, quantity_keyboard, back_only_keyboard
from keyboards.keyboards import custom_item_market_keyboard
from sqlalchemy import update
from database.models import User, House, RoleEnum
from handlers.war import is_war_time_async

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
        cfg = BotSettingsRepo(session)

        user = await user_repo.get_by_id(user_id)
        prices = await market_repo.get_all_prices()
        custom_items = await custom_repo.get_all_active()

        treasury = 0
        if user and user.house_id:
            house = await house_repo.get_by_id(user.house_id)
            treasury = house.treasury if house else 0

        # Standart qurollar stokini olish
        _stock_keys = {"soldier": "soldier_stock", "dragon": "dragon_stock", "scorpion": "scorpion_stock"}
        stocks = {}
        for key, setting_key in _stock_keys.items():
            raw = await cfg.get(setting_key)
            stocks[key] = int(raw) if raw and raw.strip().isdigit() else None

    def _stock_text(key):
        s = stocks.get(key)
        if s is None:
            return ""
        if s == 0:
            return " ❌ <i>Tugadi</i>"
        return f" (qoldi: <b>{s:,}</b>)"

    lines = [
        "🛒 <b>BOZOR</b>\n",
        f"💰 Xonadon xazinasi: <b>{treasury:,}</b> tanga\n",
        "─── Standart qurollar ───",
        f"🗡️ Askar: <b>{prices.get('soldier', 1)}</b> tanga/dona{_stock_text('soldier')}",
        f"🐉 Ajdar: <b>{prices.get('dragon', 150)}</b> tanga/dona{_stock_text('dragon')}",
        f"🏹 Skorpion: <b>{prices.get('scorpion', 25)}</b> tanga/dona{_stock_text('scorpion')}",
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
            lines.append(f"{item.emoji} {_html.escape(str(item.name) or "")}: <b>{item.price:,}</b> tanga/dona{stock_text}")

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
            lines.append(f"{item.emoji} {_html.escape(str(item.name) or "")}: {item.price:,} tanga{stock_text}")

    await callback.answer()
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=back_only_keyboard("market:back"),
        parse_mode="HTML"
    )


# ── Standart itemlar sotib olish ──────────────────────────────────────────

@router.callback_query(F.data.startswith("market:buy:"))
async def select_quantity(callback: CallbackQuery, state: FSMContext):
    if await is_war_time_async():
        await callback.answer("⚔️ Urush seansi davomida bozordan xarid qilib bo'lmaydi!", show_alert=True)
        return

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
    await _do_purchase(callback.message, callback.bot, callback.from_user.id, item, qty, state)
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
    await _do_purchase(message, message.bot, message.from_user.id, item, qty, state)


async def _do_purchase(message, bot, user_id: int, item: str, qty: int, state: FSMContext):
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)
        market_repo = MarketRepo(session)
        res_repo = HouseResourcesRepo(session)
        purchase_repo = DailyPurchaseRepo(session)

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

        # Kunlik limit tekshiruvi (dragon va scorpion uchun)
        if item in ("dragon", "scorpion"):
            res   = await res_repo.get_or_create(user.house_id)
            today = await purchase_repo.get_today(user_id, user.house_id)
            if item == "dragon":
                limit = res.dragon_buy_limit
                bought = today.dragons
                label_limit = "🐉 Ajdar kunlik limiti"
            else:
                limit = res.scorpion_buy_limit
                bought = today.scorpions
                label_limit = "🏹 Skorpion kunlik limiti"

            if bought + qty > limit:
                remaining = max(0, limit - bought)
                await message.answer(
                    f"❌ <b>{label_limit} oshib ketdi!</b>\n\n"
                    f"Kunlik limit: <b>{limit}</b> ta\n"
                    f"Bugun sotib olingan: <b>{bought}</b> ta\n"
                    f"Qolgan imkoniyat: <b>{remaining}</b> ta",
                    reply_markup=back_only_keyboard("market:back"),
                    parse_mode="HTML"
                )
                await state.clear()
                return

        # Global stok limiti tekshiruvi (BotSettings dan)
        from database.repositories import BotSettingsRepo as _BSR
        _stock_keys = {"soldier": "soldier_stock", "dragon": "dragon_stock", "scorpion": "scorpion_stock"}
        async with AsyncSessionFactory() as _ss:
            _cfg = _BSR(_ss)
            _stock_raw = await _cfg.get(_stock_keys[item])
            _stock_limit = int(_stock_raw) if _stock_raw and _stock_raw.strip().isdigit() else None

        if _stock_limit is not None and _stock_limit < qty:
            _item_labels = {"soldier": "🗡️ Askar", "dragon": "🐉 Ajdar", "scorpion": "🏹 Skorpion"}
            await message.answer(
                f"❌ <b>Stokda yetarli miqdor yo'q!</b>\n\n"
                f"{_item_labels[item]}: stokda qolgan <b>{_stock_limit:,}</b> ta\n"
                f"So'raldigan: <b>{qty:,}</b> ta",
                reply_markup=back_only_keyboard("market:back"),
                parse_mode="HTML"
            )
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
        # Kunlik xarid hisobini yangilash
        _pk = {"soldier": "soldiers", "dragon": "dragons", "scorpion": "scorpions"}
        await purchase_repo.add_purchase(user_id, user.house_id, **{_pk[item]: qty})
        await session.commit()

        # Global stokni kamaytirish (agar limit o'rnatilgan bo'lsa)
        if _stock_limit is not None:
            from database.repositories import BotSettingsRepo as _BSR2
            new_stock = max(0, _stock_limit - qty)
            async with AsyncSessionFactory() as _ss2:
                _cfg2 = _BSR2(_ss2)
                await _cfg2.set(_stock_keys[item], str(new_stock))

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
                bot,
                f"🛒 <b>BOZOR XABARI</b>\n\n"
                f"🏰 <b>{_html.escape(str(house.name) or "")}</b> xonadoni\n"
                f"{item_label}: +{qty} ta sotib oldi\n"
                f"💰 Sarflandi: {total_cost:,} tanga"
            ,
                channel="bank_market")
        except Exception:
            pass
    await state.clear()


# ── Maxsus itemlar sotib olish ────────────────────────────────────────────

@router.callback_query(F.data.startswith("market:custom:"))
async def select_custom_quantity(callback: CallbackQuery, state: FSMContext):
    if await is_war_time_async():
        await callback.answer("⚔️ Urush seansi davomida bozordan xarid qilib bo'lmaydi!", show_alert=True)
        return

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
    await _do_custom_purchase(callback.message, callback.bot, callback.from_user.id, data["custom_item_id"], qty, state)
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
    await _do_custom_purchase(message, message.bot, message.from_user.id, data["custom_item_id"], qty, state)


async def _do_custom_purchase(message, bot, user_id: int, item_id: int, qty: int, state: FSMContext):
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)
        custom_repo = CustomItemRepo(session)
        res_repo = HouseResourcesRepo(session)
        purchase_repo = DailyPurchaseRepo(session)

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

        # Kunlik custom item limiti tekshiruvi
        res   = await res_repo.get_or_create(user.house_id)
        today = await purchase_repo.get_today(user_id, user.house_id)
        if today.items + qty > res.item_buy_limit:
            remaining = max(0, res.item_buy_limit - today.items)
            await message.answer(
                f"❌ <b>Kunlik custom item limiti oshib ketdi!</b>\n\n"
                f"Kunlik limit: <b>{res.item_buy_limit}</b> ta\n"
                f"Bugun sotib olingan: <b>{today.items}</b> ta\n"
                f"Qolgan imkoniyat: <b>{remaining}</b> ta",
                reply_markup=back_only_keyboard("market:back"),
                parse_mode="HTML"
            )
            await state.clear()
            return

        # Stok cheklovini tekshirish
        if item.stock_remaining is not None:
            if item.stock_remaining == 0:
                await message.answer(
                    f"❌ <b>{item.emoji} {_html.escape(str(item.name) or "")}</b> tugab ketdi! Stokda qolmadi.",
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

        # Kunlik custom item hisobini yangilash
        await purchase_repo.add_purchase(user_id, user.house_id, items=qty)
        await session.commit()

        # Qolgan stok
        stock_info = ""
        if item.stock_remaining is not None:
            remaining = item.stock_remaining - qty
            stock_info = f"\n📦 Stokda qoldi: <b>{remaining}</b> ta"

        await message.answer(
            f"✅ <b>Muvaffaqiyatli sotib olindi!</b>\n\n"
            f"{item.emoji} {_html.escape(str(item.name) or "")}: +{qty} ta\n"
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
                bot,
                f"🛒 <b>BOZOR XABARI</b>\n\n"
                f"🏰 <b>{_html.escape(str(house.name) or "")}</b> xonadoni\n"
                f"{item.emoji} {_html.escape(str(item.name) or "")}: +{qty} ta sotib oldi\n"
                f"💰 Sarflandi: {total_cost:,} tanga"
                + (f"\n📦 Stokda qoldi: {item.stock_remaining - qty} ta" if item.stock_remaining is not None else "")
            ,
                channel="bank_market")
        except Exception:
            pass
    await state.clear()


# ─── BOSQICH 2 — KAFOLATLI XONADON (PRE-HOUSE) ────────────────────────────

@router.callback_query(F.data == "market:pre_house")
async def market_pre_house_list(callback: CallbackQuery):
    """Xonadonlarni kafolatli sotib olish sahifasi"""
    await callback.answer()

    async with AsyncSessionFactory() as session:
        from sqlalchemy import select as sa_select
        from database.models import House as HouseModel
        houses_result = await session.execute(sa_select(HouseModel))
        houses = houses_result.scalars().all()

        settings_repo = BotSettingsRepo(session)
        pre_repo = PreAssignedLordRepo(session)

        # Joriy foydalanuvchining xonadon band qilganini tekshirish
        user_repo = UserRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)

        # Foydalanuvchi allaqachon band qilgan xonadoni bor?
        my_pal = None
        for h in houses:
            pal = await pre_repo.get_by_house(h.id)
            if pal and pal.user_id == callback.from_user.id and not pal.is_applied:
                my_pal = (pal, h)
                break

        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        lines = [
            "🏰 <b>YANGI O'YIN UCHUN XONADON BAND QILISH</b>\n",
            "Siz keyingi o'yin boshlanishida lord sifatida",
            "avtomatik tayinlanishingiz uchun xonadon sotib olishingiz mumkin.\n",
            "⚠️ <i>Bu hozirgi o'yinga ta'sir qilmaydi.</i>",
            "Narxlar admin tomonidan belgilanadi.\n",
            "Xonadonlar:",
        ]

        for h in houses:
            price_str = await settings_repo.get(f"pre_house_price:{h.id}")
            price = int(price_str) if price_str else 0
            pal = await pre_repo.get_by_house(h.id)

            if pal and not pal.is_applied:
                if pal.user_id == callback.from_user.id:
                    lines.append(f"🏰 {_html.escape(str(h.name) or "")} ({h.region.value}) — {price:,} 💰  ✅ Siz band qilgansiz")
                else:
                    lines.append(f"🏰 {_html.escape(str(h.name) or "")} ({h.region.value}) — {price:,} 💰  👑 BAND")
            else:
                if price == 0:
                    lines.append(f"🏰 {_html.escape(str(h.name) or "")} ({h.region.value}) — Narx belgilanmagan")
                else:
                    lines.append(f"🏰 {_html.escape(str(h.name) or "")} ({h.region.value}) — {price:,} 💰")
                    builder.button(
                        text=f"🏰 {_html.escape(str(h.name) or "")} — {price:,} 💰",
                        callback_data=f"market:pre_house:buy:{h.id}"
                    )

    if my_pal:
        pal, house = my_pal
        lines.append(f"\n✅ Siz <b>{_html.escape(str(house.name) or "")}</b> xonadonini band qilgansiz.")

    builder.button(text="🔙 Bozor", callback_data="market:back")
    builder.adjust(1)

    try:
        await callback.message.edit_text(
            "\n".join(lines), reply_markup=builder.as_markup(), parse_mode="HTML"
        )
    except Exception:
        await callback.message.answer(
            "\n".join(lines), reply_markup=builder.as_markup(), parse_mode="HTML"
        )


@router.callback_query(F.data.startswith("market:pre_house:buy:"))
async def market_pre_house_buy_confirm(callback: CallbackQuery):
    """Xonadon band qilishni tasdiqlash"""
    house_id = int(callback.data.split(":")[-1])

    async with AsyncSessionFactory() as session:
        from sqlalchemy import select as sa_select
        from database.models import House as HouseModel
        house = (await session.execute(
            sa_select(HouseModel).where(HouseModel.id == house_id)
        )).scalar_one_or_none()

        if not house:
            await callback.answer("Xonadon topilmadi.", show_alert=True)
            return

        pre_repo = PreAssignedLordRepo(session)
        settings_repo = BotSettingsRepo(session)

        # Band qilinganmi?
        pal = await pre_repo.get_by_house(house_id)
        if pal and not pal.is_applied:
            await callback.answer("❌ Bu xonadon allaqachon band qilingan!", show_alert=True)
            return

        # Foydalanuvchi boshqa xonadon band qilganmi?
        all_houses_result = await session.execute(sa_select(HouseModel))
        all_houses = all_houses_result.scalars().all()
        for h in all_houses:
            other_pal = await pre_repo.get_by_house(h.id)
            if other_pal and other_pal.user_id == callback.from_user.id and not other_pal.is_applied:
                await callback.answer(
                    f"❌ Siz allaqachon {_html.escape(str(h.name) or "")} xonadonini band qilgansiz!",
                    show_alert=True
                )
                return

        price_str = await settings_repo.get(f"pre_house_price:{house_id}")
        price = int(price_str) if price_str else 0

        if price == 0:
            await callback.answer("❌ Bu xonadon uchun narx belgilanmagan.", show_alert=True)
            return

        # Foydalanuvchi xonadonining xazinasini tekshirish
        user_repo = UserRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)
        if not user or not user.house_id:
            await callback.answer("❌ Siz hali xonadonga qo'shilmagansiz.", show_alert=True)
            return

        house_repo = HouseRepo(session)
        user_house = await house_repo.get_by_id(user.house_id)
        if not user_house or user_house.treasury < price:
            treasury = user_house.treasury if user_house else 0
            await callback.answer(
                f"❌ Xazinada yetarli oltin yo'q!\nKerak: {price:,} | Xazina: {treasury:,}",
                show_alert=True
            )
            return

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Ha, To'layman",
                callback_data=f"market:pre_house:confirm:{house_id}"
            ),
            InlineKeyboardButton(text="❌ Bekor", callback_data="market:pre_house"),
        ]
    ])

    await callback.answer()
    await callback.message.answer(
        f"🏰 <b>{_html.escape(str(house.name) or "")}</b> xonadoniga keyingi o'yinda lord sifatida\n"
        f"kirish uchun <b>{price:,}</b> tanga to'laysizmi?\n\n"
        f"⚠️ To'lov xonadoningiz xazinasidan chiqariladi.",
        reply_markup=kb,
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("market:pre_house:confirm:"))
async def market_pre_house_buy_execute(callback: CallbackQuery):
    """Xonadon band qilish — to'lov amalga oshirish"""
    house_id = int(callback.data.split(":")[-1])

    async with AsyncSessionFactory() as session:
        try:
            from sqlalchemy import select as sa_select
            from database.models import House as HouseModel
            house = (await session.execute(
                sa_select(HouseModel).where(HouseModel.id == house_id)
            )).scalar_one_or_none()

            if not house:
                await callback.answer("Xonadon topilmadi.", show_alert=True)
                return

            pre_repo = PreAssignedLordRepo(session)
            settings_repo = BotSettingsRepo(session)

            # Yana tekshirish (race condition)
            pal = await pre_repo.get_by_house(house_id)
            if pal and not pal.is_applied:
                await callback.answer("❌ Bu xonadon allaqachon band qilingan!", show_alert=True)
                return

            price_str = await settings_repo.get(f"pre_house_price:{house_id}")
            price = int(price_str) if price_str else 0

            user_repo = UserRepo(session)
            user = await user_repo.get_by_id(callback.from_user.id)
            if not user or not user.house_id:
                await callback.answer("❌ Siz hali xonadonga qo'shilmagansiz.", show_alert=True)
                return

            user_house = (await session.execute(
                sa_select(HouseModel).where(HouseModel.id == user.house_id)
            )).scalar_one_or_none()

            if not user_house or user_house.treasury < price:
                await callback.answer("❌ Xazinada yetarli oltin yo'q!", show_alert=True)
                return

            # To'lovni amalga oshirish
            await session.execute(
                update(HouseModel)
                .where(HouseModel.id == user.house_id)
                .values(treasury=HouseModel.treasury - price)
            )
            await session.flush()

            # PreAssignedLord yozuvi
            await pre_repo.set(
                house_id=house_id,
                user_id=user.id,
                username=user.username,
                full_name=user.full_name,
                price_paid=price,
                source="market",
            )
            await session.commit()

        except Exception as e:
            await session.rollback()
            await callback.answer("❌ Xato yuz berdi. Qayta urinib ko'ring.", show_alert=True)
            return

    await callback.answer()
    await callback.message.answer(
        f"✅ <b>{_html.escape(str(house.name) or "")}</b> xonadoni muvaffaqiyatli band qilindi!\n\n"
        f"💰 To'langan: <b>{price:,}</b> tanga\n"
        f"👑 Keyingi o'yin boshlanishida siz lord sifatida tayinlanasiz.",
        parse_mode="HTML"
    )
