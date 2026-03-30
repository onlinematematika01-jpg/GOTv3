from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime
from database.engine import AsyncSessionFactory
from database.repositories import UserRepo, HouseRepo, AllianceRepo, ChronicleRepo
from database.models import RoleEnum
from keyboards import diplomacy_keyboard, house_list_keyboard, back_only_keyboard, alliance_request_keyboard
from utils.chronicle import post_to_chronicle, format_chronicle
from sqlalchemy import update
from database.models import Alliance

router = Router()


class DiploState(StatesGroup):
    selecting_ally = State()
    selecting_break = State()


@router.message(F.text == "🤝 Diplomatiya")
async def diplomacy_menu(message: Message):
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        user = await user_repo.get_by_id(message.from_user.id)

        if not user or user.role not in [RoleEnum.LORD, RoleEnum.HIGH_LORD, RoleEnum.ADMIN]:
            await message.answer("❌ Faqat Lordlar diplomatiya olib borishi mumkin.")
            return

        await message.answer(
            "🤝 <b>DIPLOMATIYA MARKAZI</b>\n\n"
            "Ittifoqlar urush vaqtida qo'llab-quvvatlashni kafolatlaydi.\n"
            "⚠️ Hukmdor urush ochsa — uning barcha ittifoqlari avtomatik buziladi.",
            reply_markup=diplomacy_keyboard(),
            parse_mode="HTML"
        )


@router.callback_query(F.data == "diplo:back")
async def diplo_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(
        "🤝 <b>DIPLOMATIYA MARKAZI</b>\n\n"
        "Ittifoqlar urush vaqtida qo'llab-quvvatlashni kafolatlaydi.\n"
        "⚠️ Hukmdor urush ochsa — uning barcha ittifoqlari avtomatik buziladi.",
        reply_markup=diplomacy_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "diplo:alliance")
async def start_alliance(callback: CallbackQuery, state: FSMContext):
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)

        if not user or user.role not in [RoleEnum.LORD, RoleEnum.HIGH_LORD]:
            await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
            return

        all_houses = await house_repo.get_all()
        others = [h for h in all_houses if h.id != user.house_id]

        await state.set_state(DiploState.selecting_ally)
        await state.update_data(my_house_id=user.house_id)

        await callback.answer()
        await callback.message.edit_text(
            "🤝 <b>Ittifoq tuzmoqchi bo'lgan xonadonni tanlang:</b>",
            reply_markup=house_list_keyboard(others, "diplo:ally", back_to="diplo:back"),
            parse_mode="HTML"
        )


@router.callback_query(DiploState.selecting_ally, F.data.startswith("diplo:ally:"))
async def confirm_alliance(callback: CallbackQuery, state: FSMContext):
    target_id = int(callback.data.split(":")[2])
    data = await state.get_data()
    my_house_id = data["my_house_id"]

    async with AsyncSessionFactory() as session:
        alliance_repo = AllianceRepo(session)
        house_repo = HouseRepo(session)

        existing = await alliance_repo.get_active(my_house_id, target_id)
        if existing:
            await callback.answer("❌ Bu xonadon bilan allaqachon ittifoqdasiz!", show_alert=True)
            await state.clear()
            return

        my_house = await house_repo.get_by_id(my_house_id)
        target_house = await house_repo.get_by_id(target_id)

        if target_house.lord_id:
            try:
                await callback.bot.send_message(
                    target_house.lord_id,
                    f"🤝 <b>ITTIFOQ TAKLIFI!</b>\n\n"
                    f"<b>{my_house.name}</b> xonadoni sizga ittifoq tuzishni taklif qilmoqda.\n\n"
                    f"Qabul qilasizmi?",
                    reply_markup=alliance_request_keyboard(my_house_id, target_id),
                    parse_mode="HTML"
                )
            except Exception:
                await callback.answer(
                    "❌ Nishon xonadonning lordiga xabar yuborib bo'lmadi.",
                    show_alert=True
                )
                await state.clear()
                return
        else:
            await callback.answer(
                "❌ Nishon xonadonning lordi topilmadi.",
                show_alert=True
            )
            await state.clear()
            return

    await state.clear()
    await callback.answer()
    await callback.message.edit_text(
        f"📨 <b>{target_house.name}</b> xonadoniga ittifoq taklifi yuborildi.\n"
        f"Ular qabul yoki rad etishini kutib turing.",
        reply_markup=back_only_keyboard("diplo:back"),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("diplo:accept:"))
async def accept_alliance(callback: CallbackQuery):
    parts = callback.data.split(":")
    from_house_id = int(parts[2])
    to_house_id = int(parts[3])

    async with AsyncSessionFactory() as session:
        alliance_repo = AllianceRepo(session)
        house_repo = HouseRepo(session)
        chronicle_repo = ChronicleRepo(session)

        existing = await alliance_repo.get_active(from_house_id, to_house_id)
        if existing:
            await callback.answer("❌ Bu ittifoq allaqachon tuzilgan!", show_alert=True)
            return

        from_house = await house_repo.get_by_id(from_house_id)
        to_house = await house_repo.get_by_id(to_house_id)

        await alliance_repo.create(from_house_id, to_house_id)

        text = format_chronicle("alliance", house1=from_house.name, house2=to_house.name)
        tg_id = await post_to_chronicle(callback.bot, text)
        await chronicle_repo.add("alliance", text, house_id=from_house_id, tg_msg_id=tg_id)

        if from_house.lord_id:
            try:
                await callback.bot.send_message(
                    from_house.lord_id,
                    f"✅ <b>ITTIFOQ TUZILDI!</b>\n\n"
                    f"<b>{to_house.name}</b> xonadoni ittifoq taklifingizni qabul qildi!",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    await callback.answer()
    await callback.message.edit_text(
        f"✅ <b>ITTIFOQ TUZILDI!</b>\n\n"
        f"<b>{from_house.name}</b> bilan ittifoq muvaffaqiyatli tuzildi!",
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("diplo:reject:"))
async def reject_alliance(callback: CallbackQuery):
    parts = callback.data.split(":")
    from_house_id = int(parts[2])
    to_house_id = int(parts[3])

    async with AsyncSessionFactory() as session:
        house_repo = HouseRepo(session)
        from_house = await house_repo.get_by_id(from_house_id)
        to_house = await house_repo.get_by_id(to_house_id)

        if from_house.lord_id:
            try:
                await callback.bot.send_message(
                    from_house.lord_id,
                    f"❌ <b>ITTIFOQ RAD ETILDI!</b>\n\n"
                    f"<b>{to_house.name}</b> xonadoni ittifoq taklifingizni rad etdi.",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    await callback.answer()
    await callback.message.edit_text(
        f"❌ <b>{from_house.name}</b> xonadonining ittifoq taklifi rad etildi.",
        parse_mode="HTML"
    )


@router.callback_query(F.data == "diplo:list")
async def list_alliances(callback: CallbackQuery):
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        alliance_repo = AllianceRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)

        if not user or not user.house_id:
            await callback.answer("❌ Xonadoningiz yo'q.", show_alert=True)
            return

        alliances = await alliance_repo.get_all_for_house(user.house_id)

        if not alliances:
            await callback.answer("Faol ittifoqlar yo'q.", show_alert=True)
            return

        text = "🤝 <b>Faol Ittifoqlar:</b>\n\n"
        for a in alliances:
            other = a.house2 if a.house1_id == user.house_id else a.house1
            text += f"• {other.name} ({other.region.value})\n"

    await callback.answer()
    await callback.message.edit_text(
        text,
        reply_markup=back_only_keyboard("diplo:back"),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "diplo:break")
async def break_alliance_start(callback: CallbackQuery, state: FSMContext):
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        alliance_repo = AllianceRepo(session)
        house_repo = HouseRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)

        if not user or not user.house_id:
            await callback.answer("❌ Xonadoningiz yo'q.", show_alert=True)
            return

        alliances = await alliance_repo.get_all_for_house(user.house_id)
        if not alliances:
            await callback.answer("Buzish uchun ittifoq yo'q.", show_alert=True)
            return

        houses = []
        for a in alliances:
            other_id = a.house2_id if a.house1_id == user.house_id else a.house1_id
            h = await house_repo.get_by_id(other_id)
            if h:
                houses.append(h)

        await state.set_state(DiploState.selecting_break)
        await state.update_data(my_house_id=user.house_id)

        await callback.answer()
        await callback.message.edit_text(
            "❌ <b>Qaysi ittifoqni buzmoqchisiz?</b>",
            reply_markup=house_list_keyboard(houses, "diplo:break_confirm", back_to="diplo:back"),
            parse_mode="HTML"
        )


@router.callback_query(DiploState.selecting_break, F.data.startswith("diplo:break_confirm:"))
async def confirm_break(callback: CallbackQuery, state: FSMContext):
    target_id = int(callback.data.split(":")[2])
    data = await state.get_data()
    my_house_id = data["my_house_id"]

    async with AsyncSessionFactory() as session:
        alliance_repo = AllianceRepo(session)
        house_repo = HouseRepo(session)

        alliance = await alliance_repo.get_active(my_house_id, target_id)
        if not alliance:
            await callback.answer("❌ Faol ittifoq topilmadi.", show_alert=True)
            await state.clear()
            return

        target = await house_repo.get_by_id(target_id)
        await session.execute(
            update(Alliance)
            .where(Alliance.id == alliance.id)
            .values(is_active=False, broken_at=datetime.utcnow())
        )
        await session.commit()

    await state.clear()
    await callback.answer()
    await callback.message.edit_text(
        f"💔 <b>{target.name}</b> bilan ittifoq buzildi.",
        reply_markup=back_only_keyboard("diplo:back"),
        parse_mode="HTML"
    )
