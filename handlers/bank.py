from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime, timedelta, timezone
from database.engine import AsyncSessionFactory
from database.repositories import UserRepo, HouseRepo, IronBankRepo, BotSettingsRepo, ChronicleRepo, IronBankDepositRepo
from sqlalchemy import update
from database.models import IronBankLoan, House
from keyboards import iron_bank_keyboard, back_only_keyboard
from config.settings import settings
from utils.chronicle import post_to_chronicle, format_chronicle
from sqlalchemy import select

router = Router()

TASHKENT = timedelta(hours=5)

class BankState(StatesGroup):
    waiting_loan_amount = State()
    waiting_repay_amount = State()

async def _get_bank_settings() -> dict:
    async with AsyncSessionFactory() as session:
        repo = BotSettingsRepo(session)
        return {
            "interest_rate": await repo.get_float("interest_rate"),
            "min_loan": await repo.get_int("bank_min_loan"),
            "max_loan": await repo.get_int("bank_max_loan"),
        }

def _bank_text(treasury: int, debt: int, cfg: dict) -> str:
    return (
        "🏦 <b>TEMIR BANK</b>\n\n"
        f"💰 Xonadon xazinasi: {treasury:,} tanga\n"
        f"📋 Qarzingiz: {debt:,} tanga\n"
        f"📈 Joriy foiz stavkasi: {cfg['interest_rate'] * 100:.0f}%\n"
        f"📊 Qarz limiti: {cfg['min_loan']:,} — {cfg['max_loan']:,} tanga\n\n"
        "⚠️ Qarz to'lanmasa — barcha qo'shin va ajdarlar musodara qilinadi!"
    )

@router.message(F.text == "🏦 Temir Bank")
async def iron_bank_menu(message: Message):
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)
        user = await user_repo.get_by_id(message.from_user.id)
        if not user:
            await message.answer("❌ Avval /start bosing.")
            return
        treasury = 0
        if user.house_id:
            house = await house_repo.get_by_id(user.house_id)
            treasury = house.treasury if house else 0
        cfg = await _get_bank_settings()
        await message.answer(
            _bank_text(treasury, user.debt, cfg),
            reply_markup=iron_bank_keyboard(),
            parse_mode="HTML"
        )

@router.callback_query(F.data == "bank:back")
async def bank_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)
        treasury = 0
        if user and user.house_id:
            house = await house_repo.get_by_id(user.house_id)
            treasury = house.treasury if house else 0
        cfg = await _get_bank_settings()
        await callback.answer()
        await callback.message.edit_text(
            _bank_text(treasury, user.debt if user else 0, cfg),
            reply_markup=iron_bank_keyboard(),
            parse_mode="HTML"
        )

@router.callback_query(F.data == "bank:loan")
async def request_loan(callback: CallbackQuery, state: FSMContext):
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)
        from database.models import RoleEnum
        if not user or user.role not in [RoleEnum.LORD, RoleEnum.HIGH_LORD, RoleEnum.ADMIN]:
            await callback.answer("❌ Faqat xonadon lordi qarz ola oladi.", show_alert=True)
            return

        # Xonadonning to'lanmagan qarzi — lord almashgan bo'lsa ham tekshiriladi
        iron_bank_repo = IronBankRepo(session)
        house_debt = await iron_bank_repo.get_house_active_debt(user.house_id)
        if house_debt > 0:
            await callback.answer(
                f"❌ Xonadoningizda to'lanmagan qarz bor!\n"
                f"Qolgan qarz: {house_debt:,} tanga\n\n"
                f"Yangi qarz olish uchun avval mavjud qarzni to'lang.",
                show_alert=True
            )
            return

    cfg = await _get_bank_settings()
    await state.set_state(BankState.waiting_loan_amount)
    await callback.answer()
    await callback.message.answer(
        f"💰 <b>Qarz miqdorini kiriting:</b>\n"
        f"📈 Foiz: {cfg['interest_rate'] * 100:.0f}%\n"
        f"📊 Limit: {cfg['min_loan']:,} — {cfg['max_loan']:,} tanga\n\n"
        f"Qarz xonadon xazinasiga tushadi.\n"
        f"Bekor qilish uchun /cancel yozing.",
        parse_mode="HTML"
    )

@router.message(BankState.waiting_loan_amount)
async def process_loan(message: Message, state: FSMContext):
    if message.text.strip().lower() == "/cancel":
        await state.clear()
        await message.answer("❌ Bekor qilindi.", reply_markup=back_only_keyboard("bank:back"))
        return

    cfg = await _get_bank_settings()
    try:
        amount = int(message.text.strip())
        if amount < cfg["min_loan"] or amount > cfg["max_loan"]:
            await message.answer(
                f"❌ Qarz miqdori {cfg['min_loan']:,} — {cfg['max_loan']:,} tanga oralig'ida bo'lishi kerak."
            )
            return
    except ValueError:
        await message.answer("❌ Iltimos, raqam kiriting.")
        return

    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)
        iron_bank_repo = IronBankRepo(session)
        chronicle_repo = ChronicleRepo(session)
        user = await user_repo.get_by_id(message.from_user.id)

        if not user:
            await message.answer("❌ Foydalanuvchi topilmadi.")
            await state.clear()
            return

        if not user.house_id:
            await message.answer("❌ Xonadoningiz yo'q.")
            await state.clear()
            return

        # Xonadonning to'lanmagan qarzi — lord almashgan bo'lsa ham tekshiriladi
        house_debt = await iron_bank_repo.get_house_active_debt(user.house_id)
        if house_debt > 0:
            await message.answer(
                f"❌ Xonadoningizda to'lanmagan qarz bor!\nQarz: {house_debt:,} tanga",
                reply_markup=back_only_keyboard("bank:back")
            )
            await state.clear()
            return

        import math
        rate = cfg["interest_rate"]
        total_due = math.ceil(amount * (1 + rate))
        due_date = datetime.utcnow() + timedelta(days=7)

        await iron_bank_repo.create_loan(user.id, user.house_id, amount, rate, due_date)

        # Xronikaga yozish va kanalga yuborish
        house = await house_repo.get_by_id(user.house_id)
        house_name = house.name if house else "Noma'lum"
        chronicle_text = format_chronicle(
            "loan",
            house=house_name,
            amount=amount,
            total_due=total_due,
        )
        tg_id = await post_to_chronicle(message.bot, chronicle_text)
        await chronicle_repo.add("loan", chronicle_text, house_id=user.house_id, tg_msg_id=tg_id)

        # Muddatni Toshkent vaqtida ko'rsatish
        due_tashkent = due_date.replace(tzinfo=timezone.utc) + TASHKENT
        await message.answer(
            f"🏦 <b>Qarz berildi!</b>\n\n"
            f"💰 Xonadon xazinasiga tushdi: {amount:,} tanga\n"
            f"📈 Foiz bilan qaytarish: {total_due:,} tanga\n"
            f"📅 To'lash muddati: {due_tashkent.strftime('%Y-%m-%d')} (Toshkent)\n\n"
            f"⚠️ Muddatda to'lamasangiz — qo'shinlaringiz musodara qilinadi!",
            reply_markup=back_only_keyboard("bank:back"),
            parse_mode="HTML"
        )

    await state.clear()

@router.callback_query(F.data == "bank:repay")
async def request_repay(callback: CallbackQuery, state: FSMContext):
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        iron_bank_repo = IronBankRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)

        if not user or not user.house_id:
            await callback.answer("❌ Xonadoningiz yo'q.", show_alert=True)
            return

        from database.models import RoleEnum
        if user.role not in [RoleEnum.LORD, RoleEnum.HIGH_LORD, RoleEnum.ADMIN]:
            await callback.answer("❌ Faqat xonadon lordi qarz to'lay oladi.", show_alert=True)
            return

        # user.debt emas — xonadonning haqiqiy qarzi (lord almashsa ham to'g'ri)
        house_debt = await iron_bank_repo.get_house_active_debt(user.house_id)
        if house_debt <= 0:
            await callback.answer("✅ Xonadoningizda qarz yo'q!", show_alert=True)
            return

    await state.set_state(BankState.waiting_repay_amount)
    await callback.answer()
    await callback.message.answer(
        f"💸 <b>Xonadon qarzi:</b> {house_debt:,} tanga\n"
        f"Xonadon xazinasidan to'lash miqdorini kiriting (yoki 'hammasi'):\n\n"
        f"Bekor qilish uchun /cancel yozing.",
        parse_mode="HTML"
    )

@router.message(BankState.waiting_repay_amount)
async def process_repay(message: Message, state: FSMContext):
    if message.text.strip().lower() == "/cancel":
        await state.clear()
        await message.answer("❌ Bekor qilindi.", reply_markup=back_only_keyboard("bank:back"))
        return

    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)
        iron_bank_repo = IronBankRepo(session)
        chronicle_repo = ChronicleRepo(session)
        user = await user_repo.get_by_id(message.from_user.id)

        if not user:
            await message.answer("❌ Foydalanuvchi topilmadi.")
            await state.clear()
            return

        if not user.house_id:
            await message.answer("❌ Xonadoningiz yo'q.")
            await state.clear()
            return

        text = message.text.strip().lower()
        if text in ["hammasi", "all", "barchasi"]:
            amount = user.debt
        else:
            try:
                amount = int(text)
                if amount <= 0:
                    raise ValueError
            except ValueError:
                await message.answer("❌ Noto'g'ri miqdor.")
                return

        result = await iron_bank_repo.repay(user, user.house_id, amount)

        if result["success"]:
            # Xronikaga yozish va kanalga yuborish
            house = await house_repo.get_by_id(user.house_id)
            house_name = house.name if house else "Noma'lum"
            chronicle_text = format_chronicle(
                "repay",
                house=house_name,
                paid=result["paid"],
                remaining=result["remaining"],
            )
            tg_id = await post_to_chronicle(message.bot, chronicle_text)
            await chronicle_repo.add("repay", chronicle_text, house_id=user.house_id, tg_msg_id=tg_id)

            await message.answer(
                f"✅ <b>Qarz to'landi!</b>\n\n"
                f"💸 Xazinadan to'landi: {result['paid']:,} tanga\n"
                f"📋 Qolgan qarz: {result['remaining']:,} tanga",
                reply_markup=back_only_keyboard("bank:back"),
                parse_mode="HTML"
            )
        else:
            await message.answer(
                f"❌ {result['reason']}",
                reply_markup=back_only_keyboard("bank:back")
            )

    await state.clear()

@router.callback_query(F.data == "bank:status")
async def bank_status(callback: CallbackQuery):
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)

        treasury = 0
        if user and user.house_id:
            house = await house_repo.get_by_id(user.house_id)
            treasury = house.treasury if house else 0

        result = await session.execute(
            select(IronBankLoan).where(
                IronBankLoan.user_id == callback.from_user.id,
                IronBankLoan.paid == False,
            )
        )
        loans = result.scalars().all()

        text = (
            f"🏦 <b>Temir Bank Holati</b>\n\n"
            f"💰 Xonadon xazinasi: {treasury:,} tanga\n"
            f"📋 Jami qarz: {user.debt:,}\n\n"
        )
        if loans:
            text += "<b>Faol qarzlar:</b>\n"
            for loan in loans:
                if loan.due_date:
                    due_tashkent = loan.due_date.replace(tzinfo=timezone.utc) + TASHKENT
                    due_str = due_tashkent.strftime('%Y-%m-%d')
                else:
                    due_str = "N/A"
                text += (
                    f"• {loan.principal:,} → {loan.total_due:,} tanga "
                    f"({loan.interest_rate*100:.0f}% foiz)\n"
                    f"  Muddat: {due_str}\n"
                )
        else:
            text += "✅ Faol qarzlar yo'q."

        await callback.answer()
        await callback.message.edit_text(
            text,
            reply_markup=back_only_keyboard("bank:back"),
            parse_mode="HTML"
        )


# ═══════════════════════════════════════════════════════
#  OMONAT TIZIMI
# ═══════════════════════════════════════════════════════

# Harbiy narxlar (settings dan)
def _military_value(soldiers: int, dragons: int, scorpions: int,
                    s_price: int = None, d_price: int = None, sc_price: int = None) -> int:
    return (
        soldiers  * (s_price  if s_price  is not None else settings.SOLDIER_PRICE) +
        dragons   * (d_price  if d_price  is not None else settings.DRAGON_PRICE)  +
        scorpions * (sc_price if sc_price is not None else settings.SCORPION_PRICE)
    )


async def _get_market_prices(session) -> tuple:
    """Bozordagi joriy harbiy narxlarni qaytaradi: (askar, ajdar, skorpion)"""
    from database.repositories import MarketRepo
    market_repo = MarketRepo(session)
    prices = await market_repo.get_all_prices()
    s  = prices.get("soldier",  settings.SOLDIER_PRICE)
    d  = prices.get("dragon",   settings.DRAGON_PRICE)
    sc = prices.get("scorpion", settings.SCORPION_PRICE)
    return s, d, sc


class DepositState(StatesGroup):
    waiting_gold      = State()
    waiting_soldiers  = State()
    waiting_dragons   = State()
    waiting_scorpions = State()


async def _get_deposit_settings() -> dict:
    async with AsyncSessionFactory() as session:
        repo = BotSettingsRepo(session)
        return {
            "rate_per_day":  await repo.get_float("deposit_rate_per_day"),
            "duration_days": await repo.get_int("deposit_duration_days"),
        }


@router.callback_query(F.data == "bank:deposit_menu")
async def deposit_menu(callback: CallbackQuery):
    from database.repositories import IronBankDepositRepo
    from database.models import RoleEnum
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)
        if not user or not user.house_id:
            await callback.answer("❌ Xonadoningiz yo'q.", show_alert=True)
            return
        house = await house_repo.get_by_id(user.house_id)
        dep_repo = IronBankDepositRepo(session)
        deposit = await dep_repo.get_active(user.house_id)
        cfg = await _get_deposit_settings()
        s_price, d_price, sc_price = await _get_market_prices(session)

    rate_pct = cfg["rate_per_day"] * 100
    days = cfg["duration_days"]
    total_pct = rate_pct * days

    if deposit:
        from datetime import datetime, timezone
        expires_tz = deposit.expires_at.replace(tzinfo=timezone.utc) + TASHKENT
        days_left = max(0, (deposit.expires_at - datetime.utcnow()).days)
        mil_val = _military_value(deposit.soldiers, deposit.dragons, deposit.scorpions,
                                  s_price, d_price, sc_price)
        text = (
            "🏦 <b>TEMIR BANK — OMONAT</b>\n\n"
            "📦 <b>Faol omonat:</b>\n"
            f"💰 Oltin: {deposit.gold:,} tanga\n"
            f"🗡️ Askarlar: {deposit.soldiers:,} ({deposit.soldiers * s_price:,} tanga)\n"
            f"🐉 Ajdarlar: {deposit.dragons:,} ({deposit.dragons * d_price:,} tanga)\n"
            f"🏹 Skorpionlar: {deposit.scorpions:,} ({deposit.scorpions * sc_price:,} tanga)\n"
            f"📊 Umumiy omonat: <b>{deposit.gold + mil_val:,} tanga</b>\n\n"
            f"📅 Muddat tugashi: {expires_tz.strftime('%Y-%m-%d')} (Toshkent)\n"
            f"⏳ Qolgan kun: {days_left}\n\n"
            f"📈 Kunlik foiz: {rate_pct:.1f}% (umumiy summadan)\n"
            "🛡️ Omonat urushdan himoyalangan!"
        )
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📤 Omonatni yopish", callback_data="bank:deposit_close")],
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="bank:back")],
        ])
    else:
        text = (
            "🏦 <b>TEMIR BANK — OMONAT</b>\n\n"
            f"📈 Kunlik foiz: <b>{rate_pct:.1f}%</b>\n"
            f"📅 Muddat: <b>{days} kun</b>\n"
            f"💹 Jami foiz: <b>{total_pct:.1f}%</b>\n\n"
            "📦 Omonatga qo'yilgan resurslar urush paytida <b>himoyalangan</b> va jangda qatnashmaydi.\n"
            "💰 Foiz kunlik ravishda xazinaga tushadi.\n\n"
            f"🏦 Xazina: {house.treasury:,} tanga\n"
            f"🗡️ Askarlar: {house.total_soldiers:,}\n"
            f"🐉 Ajdarlar: {house.total_dragons:,}\n"
            f"🏹 Skorpionlar: {house.total_scorpions:,}"
        )
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📥 Omonat ochish", callback_data="bank:deposit_start")],
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="bank:back")],
        ])

    await callback.answer()
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "bank:deposit_start")
async def deposit_start(callback: CallbackQuery, state: FSMContext):
    from database.models import RoleEnum
    from database.repositories import IronBankDepositRepo
    from handlers.war import is_war_time_async

    # Urush seansi vaqtida omonat ochish taqiqlangan
    if await is_war_time_async():
        await callback.answer(
            "⚔️ Urush seansi davomida omonat ochib bo'lmaydi!\n"
            "Urush tugagandan so'ng urinib ko'ring.",
            show_alert=True
        )
        return

    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)
        if not user or user.role not in [RoleEnum.LORD, RoleEnum.HIGH_LORD]:
            await callback.answer("❌ Faqat xonadon lordi omonat ocha oladi.", show_alert=True)
            return
        dep_repo = IronBankDepositRepo(session)
        existing = await dep_repo.get_active(user.house_id)
        if existing:
            await callback.answer("❌ Allaqachon faol omonat mavjud.", show_alert=True)
            return
        house = await house_repo.get_by_id(user.house_id)
        await state.update_data(house_id=user.house_id)

    cfg = await _get_deposit_settings()
    await state.set_state(DepositState.waiting_gold)
    await callback.answer()
    await callback.message.answer(
        f"📥 <b>Omonat ochish</b>\n\n"
        f"📈 Kunlik foiz: <b>{cfg['rate_per_day']*100:.1f}%</b>  |  📅 Muddat: <b>{cfg['duration_days']} kun</b>\n\n"
        f"💡 Foiz umumiy omonat summasidan hisoblanadi:\n"
        f"  🗡️ 1 askar = {settings.SOLDIER_PRICE} tanga\n"
        f"  🐉 1 ajdar = {settings.DRAGON_PRICE} tanga\n"
        f"  🏹 1 skorpion = {settings.SCORPION_PRICE} tanga\n\n"
        f"💰 Xazinadan omonatga qo'ymoqchi bo'lgan <b>oltin miqdorini</b> kiriting:\n"
        f"(0 — oltin qo'ymaslik)\n\n"
        f"Bekor qilish: /cancel",
        parse_mode="HTML"
    )


@router.message(DepositState.waiting_gold)
async def deposit_gold(message: Message, state: FSMContext):
    if message.text.strip().lower() == "/cancel":
        await state.clear()
        await message.answer("❌ Bekor qilindi.")
        return
    try:
        amount = int(message.text.strip())
        if amount < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Noto'g'ri raqam. Qayta kiriting:")
        return

    async with AsyncSessionFactory() as session:
        house_repo = HouseRepo(session)
        data = await state.get_data()
        house = await house_repo.get_by_id(data["house_id"])
        if amount > house.treasury:
            await message.answer(f"❌ Xazinada {house.treasury:,} tanga bor. Kamroq kiriting:")
            return
        if amount > 0:
            await session.execute(
                update(House).where(House.id == house.id).values(treasury=House.treasury - amount)
            )
            await session.commit()

    await state.update_data(gold=amount)
    await state.set_state(DepositState.waiting_soldiers)
    await message.answer(
        f"✅ Oltin: {amount:,}\n\n"
        f"🗡️ Omonatga qo'ymoqchi bo'lgan <b>askar soni</b>ni kiriting:\n"
        f"(0 — askar qo'ymaslik)"
    )


@router.message(DepositState.waiting_soldiers)
async def deposit_soldiers(message: Message, state: FSMContext):
    if message.text.strip().lower() == "/cancel":
        # Oltinni qaytarish
        data = await state.get_data()
        async with AsyncSessionFactory() as session:
            await session.execute(
                update(House).where(House.id == data["house_id"]).values(
                    treasury=House.treasury + data.get("gold", 0)
                )
            )
            await session.commit()
        await state.clear()
        await message.answer("❌ Bekor qilindi. Oltin qaytarildi.")
        return
    try:
        amount = int(message.text.strip())
        if amount < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Noto'g'ri raqam:")
        return

    async with AsyncSessionFactory() as session:
        house_repo = HouseRepo(session)
        data = await state.get_data()
        house = await house_repo.get_by_id(data["house_id"])
        if amount > house.total_soldiers:
            await message.answer(f"❌ Xonadoningizda {house.total_soldiers:,} askar bor:")
            return
        if amount > 0:
            await house_repo.update_military(house.id, soldiers=-amount)

    await state.update_data(soldiers=amount)
    await state.set_state(DepositState.waiting_dragons)
    await message.answer(
        f"✅ Askarlar: {amount:,}\n\n"
        f"🐉 Omonatga qo'ymoqchi bo'lgan <b>ajdar soni</b>ni kiriting:\n"
        f"(0 — ajdar qo'ymaslik)"
    )


@router.message(DepositState.waiting_dragons)
async def deposit_dragons(message: Message, state: FSMContext):
    if message.text.strip().lower() == "/cancel":
        data = await state.get_data()
        async with AsyncSessionFactory() as session:
            house_repo = HouseRepo(session)
            await session.execute(
                update(House).where(House.id == data["house_id"]).values(
                    treasury=House.treasury + data.get("gold", 0)
                )
            )
            await house_repo.update_military(data["house_id"], soldiers=data.get("soldiers", 0))
            await session.commit()
        await state.clear()
        await message.answer("❌ Bekor qilindi. Resurslar qaytarildi.")
        return
    try:
        amount = int(message.text.strip())
        if amount < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Noto'g'ri raqam:")
        return

    async with AsyncSessionFactory() as session:
        house_repo = HouseRepo(session)
        data = await state.get_data()
        house = await house_repo.get_by_id(data["house_id"])
        if amount > house.total_dragons:
            await message.answer(f"❌ Xonadoningizda {house.total_dragons:,} ajdar bor:")
            return
        if amount > 0:
            await house_repo.update_military(house.id, dragons=-amount)

    await state.update_data(dragons=amount)
    await state.set_state(DepositState.waiting_scorpions)
    await message.answer(
        f"✅ Ajdarlar: {amount:,}\n\n"
        f"🏹 Omonatga qo'ymoqchi bo'lgan <b>skorpion soni</b>ni kiriting:\n"
        f"(0 — skorpion qo'ymaslik)"
    )


@router.message(DepositState.waiting_scorpions)
async def deposit_scorpions(message: Message, state: FSMContext):
    if message.text.strip().lower() == "/cancel":
        data = await state.get_data()
        async with AsyncSessionFactory() as session:
            house_repo = HouseRepo(session)
            await session.execute(
                update(House).where(House.id == data["house_id"]).values(
                    treasury=House.treasury + data.get("gold", 0)
                )
            )
            await house_repo.update_military(
                data["house_id"],
                soldiers=data.get("soldiers", 0),
                dragons=data.get("dragons", 0),
            )
            await session.commit()
        await state.clear()
        await message.answer("❌ Bekor qilindi. Resurslar qaytarildi.")
        return
    try:
        amount = int(message.text.strip())
        if amount < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Noto'g'ri raqam:")
        return

    async with AsyncSessionFactory() as session:
        house_repo = HouseRepo(session)
        dep_repo = IronBankDepositRepo(session)
        data = await state.get_data()
        house = await house_repo.get_by_id(data["house_id"])
        if amount > house.total_scorpions:
            await message.answer(f"❌ Xonadoningizda {house.total_scorpions:,} skorpion bor:")
            return
        if amount > 0:
            await house_repo.update_military(house.id, scorpions=-amount)

        cfg = await _get_deposit_settings()
        s_price, d_price, sc_price = await _get_market_prices(session)
        gold_in = data.get("gold", 0)
        soldiers_in = data.get("soldiers", 0)
        dragons_in = data.get("dragons", 0)
        scorpions_in = amount
        dep = await dep_repo.create(
            house_id=data["house_id"],
            gold=gold_in,
            soldiers=soldiers_in,
            dragons=dragons_in,
            scorpions=scorpions_in,
            rate_per_day=cfg["rate_per_day"],
            duration_days=cfg["duration_days"],
        )

    from datetime import datetime, timezone
    expires_tz = dep.expires_at.replace(tzinfo=timezone.utc) + TASHKENT
    mil_val = _military_value(dep.soldiers, dep.dragons, dep.scorpions, s_price, d_price, sc_price)
    total_val = dep.gold + mil_val
    await state.clear()
    await message.answer(
        f"✅ <b>Omonat muvaffaqiyatli ochildi!</b>\n\n"
        f"💰 Oltin: {dep.gold:,} tanga\n"
        f"🗡️ Askarlar: {dep.soldiers:,} ({dep.soldiers * s_price:,} tanga)\n"
        f"🐉 Ajdarlar: {dep.dragons:,} ({dep.dragons * d_price:,} tanga)\n"
        f"🏹 Skorpionlar: {dep.scorpions:,} ({dep.scorpions * sc_price:,} tanga)\n"
        f"📊 Umumiy omonat: <b>{total_val:,} tanga</b>\n\n"
        f"📈 Kunlik foiz: {dep.interest_rate_per_day*100:.1f}%\n"
        f"📅 Muddat: {dep.duration_days} kun\n"
        f"🗓️ Tugash sanasi: {expires_tz.strftime('%Y-%m-%d')}\n\n"
        f"🛡️ Omonatdagi resurslar urushdan himoyalangan!",
        parse_mode="HTML"
    )


@router.callback_query(F.data == "bank:deposit_close")
async def deposit_close(callback: CallbackQuery):
    from database.models import RoleEnum
    from database.repositories import IronBankDepositRepo
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)
        if not user or user.role not in [RoleEnum.LORD, RoleEnum.HIGH_LORD]:
            await callback.answer("❌ Faqat xonadon lordi omonatni yopa oladi.", show_alert=True)
            return
        dep_repo = IronBankDepositRepo(session)
        deposit = await dep_repo.get_active(user.house_id)
        if not deposit:
            await callback.answer("❌ Faol omonat topilmadi.", show_alert=True)
            return
        s_price, d_price, sc_price = await _get_market_prices(session)
        interest = await dep_repo.close(deposit, pay_interest=True,
                                        s_price=s_price, d_price=d_price, sc_price=sc_price)

    await callback.answer()
    await callback.message.edit_text(
        f"📤 <b>Omonat yopildi!</b>\n\n"
        f"💰 Oltin qaytarildi: {deposit.gold:,} tanga\n"
        f"🗡️ Askarlar qaytarildi: {deposit.soldiers:,}\n"
        f"🐉 Ajdarlar qaytarildi: {deposit.dragons:,}\n"
        f"🏹 Skorpionlar qaytarildi: {deposit.scorpions:,}\n"
        f"📈 Foiz daromadi: +{interest:,} tanga\n\n"
        f"✅ Barcha resurslar xonadoningizga qaytarildi!",
        parse_mode="HTML"
    )
