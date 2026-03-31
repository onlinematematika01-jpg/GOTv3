from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime, timedelta, timezone
from database.engine import AsyncSessionFactory
from database.repositories import UserRepo, HouseRepo, IronBankRepo, BotSettingsRepo, ChronicleRepo
from database.models import IronBankLoan
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
        user = await user_repo.get_by_id(callback.from_user.id)

        if not user or user.debt <= 0:
            await callback.answer("✅ Qarzingiz yo'q!", show_alert=True)
            return

        from database.models import RoleEnum
        if user.role not in [RoleEnum.LORD, RoleEnum.HIGH_LORD, RoleEnum.ADMIN]:
            await callback.answer("❌ Faqat xonadon lordi qarz to'lay oladi.", show_alert=True)
            return

    await state.set_state(BankState.waiting_repay_amount)
    await callback.answer()
    await callback.message.answer(
        f"💸 <b>Qarzingiz:</b> {user.debt:,} tanga\n"
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
