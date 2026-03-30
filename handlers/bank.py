from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime, timedelta
from database.engine import AsyncSessionFactory
from database.repositories import UserRepo, IronBankRepo, BotSettingsRepo
from database.models import IronBankLoan
from keyboards import iron_bank_keyboard, back_only_keyboard
from config.settings import settings
from sqlalchemy import select

router = Router()


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


@router.message(F.text == "🏦 Temir Bank")
async def iron_bank_menu(message: Message):
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        user = await user_repo.get_by_id(message.from_user.id)
        if not user:
            await message.answer("❌ Avval /start bosing.")
            return
        cfg = await _get_bank_settings()
        text = (
            "🏦 <b>TEMIR BANK</b>\n\n"
            f"💰 Sizning oltiningiz: {user.gold:,}\n"
            f"📋 Qarzingiz: {user.debt:,} tanga\n"
            f"📈 Joriy foiz stavkasi: {cfg['interest_rate'] * 100:.0f}%\n"
            f"📊 Qarz limiti: {cfg['min_loan']:,} — {cfg['max_loan']:,} tanga\n\n"
            "⚠️ Qarz to'lanmasa — barcha qo'shin va ajdarlar musodara qilinadi!"
        )
        await message.answer(text, reply_markup=iron_bank_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "bank:back")
async def bank_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)
    cfg = await _get_bank_settings()
    text = (
        "🏦 <b>TEMIR BANK</b>\n\n"
        f"💰 Sizning oltiningiz: {user.gold:,}\n"
        f"📋 Qarzingiz: {user.debt:,} tanga\n"
        f"📈 Joriy foiz stavkasi: {cfg['interest_rate'] * 100:.0f}%\n"
        f"📊 Qarz limiti: {cfg['min_loan']:,} — {cfg['max_loan']:,} tanga\n\n"
        "⚠️ Qarz to'lanmasa — barcha qo'shin va ajdarlar musodara qilinadi!"
    )
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=iron_bank_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "bank:loan")
async def request_loan(callback: CallbackQuery, state: FSMContext):
    cfg = await _get_bank_settings()
    await state.set_state(BankState.waiting_loan_amount)
    await callback.answer()
    await callback.message.answer(
        f"💰 <b>Qarz miqdorini kiriting:</b>\n"
        f"📈 Foiz: {cfg['interest_rate'] * 100:.0f}%\n"
        f"📊 Limit: {cfg['min_loan']:,} — {cfg['max_loan']:,} tanga\n\n"
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
        iron_bank_repo = IronBankRepo(session)
        user = await user_repo.get_by_id(message.from_user.id)

        if not user:
            await message.answer("❌ Foydalanuvchi topilmadi.")
            await state.clear()
            return

        if user.debt > 0:
            await message.answer(
                f"❌ Avvalgi qarzingizni to'lang!\nQarz: {user.debt:,} tanga",
                reply_markup=back_only_keyboard("bank:back")
            )
            await state.clear()
            return

        import math
        rate = cfg["interest_rate"]
        total_due = math.ceil(amount * (1 + rate))
        due_date = datetime.utcnow() + timedelta(days=7)

        await iron_bank_repo.create_loan(user.id, amount, rate, due_date)

        await message.answer(
            f"🏦 <b>Qarz berildi!</b>\n\n"
            f"💰 Olingan: {amount:,} tanga\n"
            f"📈 Foiz bilan: {total_due:,} tanga\n"
            f"📅 To'lash muddati: {due_date.strftime('%Y-%m-%d')}\n\n"
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

    await state.set_state(BankState.waiting_repay_amount)
    await callback.answer()
    await callback.message.answer(
        f"💸 <b>Qarzingiz:</b> {user.debt:,} tanga\n"
        f"To'lash miqdorini kiriting (yoki 'hammasi'):\n\n"
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
        iron_bank_repo = IronBankRepo(session)
        user = await user_repo.get_by_id(message.from_user.id)

        if not user:
            await message.answer("❌ Foydalanuvchi topilmadi.")
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

        result = await iron_bank_repo.repay(user, amount)

        if result["success"]:
            await message.answer(
                f"✅ <b>Qarz to'landi!</b>\n\n"
                f"💸 To'landi: {result['paid']:,} tanga\n"
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
        user = await user_repo.get_by_id(callback.from_user.id)

        result = await session.execute(
            select(IronBankLoan).where(
                IronBankLoan.user_id == callback.from_user.id,
                IronBankLoan.paid == False,
            )
        )
        loans = result.scalars().all()

        text = f"🏦 <b>Temir Bank Holati</b>\n\n💰 Oltin: {user.gold:,}\n📋 Jami qarz: {user.debt:,}\n\n"
        if loans:
            text += "<b>Faol qarzlar:</b>\n"
            for loan in loans:
                text += (
                    f"• {loan.principal:,} → {loan.total_due:,} tanga "
                    f"({loan.interest_rate*100:.0f}% foiz)\n"
                    f"  Muddat: {loan.due_date.strftime('%Y-%m-%d') if loan.due_date else 'N/A'}\n"
                )
        else:
            text += "✅ Faol qarzlar yo'q."

    await callback.answer()
    await callback.message.edit_text(
        text,
        reply_markup=back_only_keyboard("bank:back"),
        parse_mode="HTML"
    )


class BankState(StatesGroup):
    waiting_loan_amount = State()
    waiting_repay_amount = State()


@router.message(F.text == "🏦 Temir Bank")
async def iron_bank_menu(message: Message):
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        user = await user_repo.get_by_id(message.from_user.id)

        if not user:
            await message.answer("❌ Avval /start bosing.")
            return

        text = (
            "🏦 <b>TEMIR BANK</b>\n\n"
            f"💰 Sizning oltiningiz: {user.gold:,}\n"
            f"📋 Qarzingiz: {user.debt:,} tanga\n"
            f"📈 Joriy foiz stavkasi: {CURRENT_INTEREST_RATE * 100:.0f}%\n"
            f"📊 Qarz limiti: {BANK_MIN_LOAN:,} — {BANK_MAX_LOAN:,} tanga\n\n"
            "⚠️ Qarz to'lanmasa — barcha qo'shin va ajdarlar musodara qilinadi!"
        )
        await message.answer(text, reply_markup=iron_bank_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "bank:back")
async def bank_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)
    text = (
        "🏦 <b>TEMIR BANK</b>\n\n"
        f"💰 Sizning oltiningiz: {user.gold:,}\n"
        f"📋 Qarzingiz: {user.debt:,} tanga\n"
        f"📈 Joriy foiz stavkasi: {CURRENT_INTEREST_RATE * 100:.0f}%\n"
        f"📊 Qarz limiti: {BANK_MIN_LOAN:,} — {BANK_MAX_LOAN:,} tanga\n\n"
        "⚠️ Qarz to'lanmasa — barcha qo'shin va ajdarlar musodara qilinadi!"
    )
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=iron_bank_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "bank:loan")
async def request_loan(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BankState.waiting_loan_amount)
    await callback.answer()
    await callback.message.answer(
        f"💰 <b>Qarz miqdorini kiriting:</b>\n"
        f"📈 Foiz: {CURRENT_INTEREST_RATE * 100:.0f}%\n"
        f"📊 Limit: {BANK_MIN_LOAN:,} — {BANK_MAX_LOAN:,} tanga\n\n"
        f"Bekor qilish uchun /cancel yozing.",
        parse_mode="HTML"
    )


@router.message(BankState.waiting_loan_amount)
async def process_loan(message: Message, state: FSMContext):
    if message.text.strip().lower() == "/cancel":
        await state.clear()
        await message.answer("❌ Bekor qilindi.", reply_markup=back_only_keyboard("bank:back"))
        return

    try:
        amount = int(message.text.strip())
        if amount < BANK_MIN_LOAN or amount > BANK_MAX_LOAN:
            await message.answer(
                f"❌ Qarz miqdori {BANK_MIN_LOAN:,} — {BANK_MAX_LOAN:,} tanga oralig'ida bo'lishi kerak."
            )
            return
    except ValueError:
        await message.answer("❌ Iltimos, raqam kiriting.")
        return

    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        iron_bank_repo = IronBankRepo(session)
        user = await user_repo.get_by_id(message.from_user.id)

        if not user:
            await message.answer("❌ Foydalanuvchi topilmadi.")
            await state.clear()
            return

        if user.debt > 0:
            await message.answer(
                f"❌ Avvalgi qarzingizni to'lang!\nQarz: {user.debt:,} tanga",
                reply_markup=back_only_keyboard("bank:back")
            )
            await state.clear()
            return

        due_date = datetime.utcnow() + timedelta(days=7)
        import math
        total_due = math.ceil(amount * (1 + CURRENT_INTEREST_RATE))

        await iron_bank_repo.create_loan(user.id, amount, CURRENT_INTEREST_RATE, due_date)

        await message.answer(
            f"🏦 <b>Qarz berildi!</b>\n\n"
            f"💰 Olingan: {amount:,} tanga\n"
            f"📈 Foiz bilan: {total_due:,} tanga\n"
            f"📅 To'lash muddati: {due_date.strftime('%Y-%m-%d')}\n\n"
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

    await state.set_state(BankState.waiting_repay_amount)
    await callback.answer()
    await callback.message.answer(
        f"💸 <b>Qarzingiz:</b> {user.debt:,} tanga\n"
        f"To'lash miqdorini kiriting (yoki 'hammasi'):\n\n"
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
        iron_bank_repo = IronBankRepo(session)
        user = await user_repo.get_by_id(message.from_user.id)

        if not user:
            await message.answer("❌ Foydalanuvchi topilmadi.")
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

        result = await iron_bank_repo.repay(user, amount)

        if result["success"]:
            await message.answer(
                f"✅ <b>Qarz to'landi!</b>\n\n"
                f"💸 To'landi: {result['paid']:,} tanga\n"
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
        user = await user_repo.get_by_id(callback.from_user.id)

        result = await session.execute(
            select(IronBankLoan).where(
                IronBankLoan.user_id == callback.from_user.id,
                IronBankLoan.paid == False,
            )
        )
        loans = result.scalars().all()

        text = f"🏦 <b>Temir Bank Holati</b>\n\n💰 Oltin: {user.gold:,}\n📋 Jami qarz: {user.debt:,}\n\n"
        if loans:
            text += "<b>Faol qarzlar:</b>\n"
            for loan in loans:
                text += (
                    f"• {loan.principal:,} → {loan.total_due:,} tanga "
                    f"({loan.interest_rate*100:.0f}% foiz)\n"
                    f"  Muddat: {loan.due_date.strftime('%Y-%m-%d') if loan.due_date else 'N/A'}\n"
                )
        else:
            text += "✅ Faol qarzlar yo'q."

    await callback.answer()
    await callback.message.edit_text(
        text,
        reply_markup=back_only_keyboard("bank:back"),
        parse_mode="HTML"
    )
