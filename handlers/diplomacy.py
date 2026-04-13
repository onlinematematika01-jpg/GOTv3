from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database.engine import AsyncSessionFactory
from database.repositories import UserRepo, HouseRepo, AllianceGroupRepo
from database.models import RoleEnum
from keyboards import (
    diplomacy_keyboard, back_only_keyboard, house_list_keyboard,
    alliance_group_menu_keyboard, alliance_invite_keyboard
)

router = Router()

MAX_MEMBERS = 3


class DiploState(StatesGroup):
    entering_group_name = State()
    entering_new_name = State()
    selecting_invite_target = State()


# ─── ASOSIY MENYU ────────────────────────────────────────────────────────────

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
        "Ittifoq guruhida 2 dan 3 tagacha xonadon birlashadi.\n"
        "Faqat <b>bir hududdagi</b> xonadonlar ittifoq tuzishi mumkin.\n"
        "Bir xonadon faqat bitta ittifoq guruhida bo'la oladi.",
        reply_markup=diplomacy_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "diplo:back_main")
async def diplo_back_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(
        "🤝 <b>DIPLOMATIYA MARKAZI</b>\n\n"
        "Ittifoq guruhida 2 dan 3 tagacha xonadon birlashadi.\n"
        "Faqat <b>bir hududdagi</b> xonadonlar ittifoq tuzishi mumkin.\n"
        "Bir xonadon faqat bitta ittifoq guruhida bo'la oladi.",
        reply_markup=diplomacy_keyboard(),
        parse_mode="HTML"
    )


# ─── GURUH MENYUSI ───────────────────────────────────────────────────────────

@router.callback_query(F.data == "diplo:group_menu")
async def group_menu(callback: CallbackQuery):
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)
        if not user or not user.house_id:
            await callback.answer("❌ Xonadoningiz yo'q.", show_alert=True)
            return

        group_repo = AllianceGroupRepo(session)
        group = await group_repo.get_house_active_group(user.house_id)
        in_group = group is not None
        is_leader = in_group and group.leader_house_id == user.house_id

        if in_group:
            member_lines = "\n".join(
                f"  {'👑' if m.house_id == group.leader_house_id else '⚔️'} {m.house.name}"
                for m in group.members
            )
            text = (
                f"🏰 <b>ITTIFOQ GURUHI</b>\n\n"
                f"📛 Nomi: <b>{group.name}</b>\n"
                f"👥 A'zolar ({len(group.members)}/{MAX_MEMBERS}):\n{member_lines}"
            )
        else:
            text = (
                "🏰 <b>ITTIFOQ GURUHI</b>\n\n"
                "Siz hozirda hech qanday ittifoq guruhida emassiz.\n"
                "Yangi guruh tuzing yoki taklif kutib turing."
            )

    await callback.answer()
    await callback.message.edit_text(
        text,
        reply_markup=alliance_group_menu_keyboard(in_group, is_leader),
        parse_mode="HTML"
    )


# ─── GURUH TUZISH ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "diplo:group_create")
async def group_create_start(callback: CallbackQuery, state: FSMContext):
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)
        if not user or user.role not in [RoleEnum.LORD, RoleEnum.HIGH_LORD, RoleEnum.ADMIN]:
            await callback.answer("❌ Faqat Lordlar ittifoq tuzishi mumkin.", show_alert=True)
            return
        if not user.house_id:
            await callback.answer("❌ Xonadoningiz yo'q.", show_alert=True)
            return

        group_repo = AllianceGroupRepo(session)
        existing = await group_repo.get_house_active_group(user.house_id)
        if existing:
            await callback.answer("❌ Siz allaqachon ittifoq guruhidasiz.", show_alert=True)
            return
        house_id = user.house_id
        house_repo = HouseRepo(session)
        my_house = await house_repo.get_by_id(house_id)
        house_region = my_house.region if my_house else None

    await state.set_state(DiploState.entering_group_name)
    await state.update_data(house_id=house_id, house_region=house_region.value if house_region else None)
    await callback.answer()
    await callback.message.edit_text(
        "📛 <b>Ittifoq guruhingiz nomini kiriting:</b>\n\n"
        "(2–40 ta belgi, masalan: <i>Shimoliy Ittifoq</i>)",
        parse_mode="HTML"
    )


@router.message(DiploState.entering_group_name)
async def group_create_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2 or len(name) > 40:
        await message.answer("❌ Nom 2 dan 40 gacha belgi bo'lishi kerak. Qaytadan kiriting:")
        return

    data = await state.get_data()
    house_id = data["house_id"]
    house_region = data.get("house_region", "")

    async with AsyncSessionFactory() as session:
        group_repo = AllianceGroupRepo(session)
        group = await group_repo.create_group(name=name, leader_house_id=house_id)

    await state.clear()
    await message.answer(
        f"✅ <b>«{group.name}»</b> ittifoq guruhi tuzildi!\n\n"
        f"📍 Hudud: <b>{house_region}</b>\n"
        f"Faqat shu hududdagi xonadonlarga taklif yuborishingiz mumkin.\n"
        f"Guruhda maksimal {MAX_MEMBERS} ta xonadon bo'la oladi.",
        parse_mode="HTML",
        reply_markup=alliance_group_menu_keyboard(in_group=True, is_leader=True)
    )


# ─── TAKLIF YUBORISH ──────────────────────────────────────────────────────

@router.callback_query(F.data == "diplo:group_invite")
async def group_invite_start(callback: CallbackQuery, state: FSMContext):
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)
        if not user or not user.house_id:
            await callback.answer("❌ Xonadoningiz yo'q.", show_alert=True)
            return

        group_repo = AllianceGroupRepo(session)
        group = await group_repo.get_house_active_group(user.house_id)
        if not group or group.leader_house_id != user.house_id:
            await callback.answer("❌ Siz guruh tashkilotchisi emassiz.", show_alert=True)
            return
        if len(group.members) >= MAX_MEMBERS:
            await callback.answer(
                f"❌ Guruhda allaqachon {MAX_MEMBERS} ta xonadon bor. Joy yo'q.",
                show_alert=True
            )
            return

        # Tashkilotchining hududini aniqlash
        my_house = await house_repo.get_by_id(user.house_id)
        my_region = my_house.region if my_house else None

        member_ids = {m.house_id for m in group.members}
        region_houses = await house_repo.get_all_by_region(my_region) if my_region else []
        candidates = []
        for h in region_houses:
            if h.id in member_ids:
                continue
            other_group = await group_repo.get_house_active_group(h.id)
            if other_group:
                continue
            candidates.append(h)

        group_id = group.id
        group_member_count = len(group.members)
        my_house_id = user.house_id
        region_name = my_region.value if my_region else ""

    if not candidates:
        await callback.answer(
            f"❌ {region_name} hududida taklif yuborish mumkin bo'lgan xonadon yo'q. "
            "Boshqa xonadonlar allaqachon ittifoqlarda yoki bu hududda boshqa xonadon yo'q.",
            show_alert=True
        )
        return

    await state.set_state(DiploState.selecting_invite_target)
    await state.update_data(group_id=group_id, my_house_id=my_house_id)
    await callback.answer()
    await callback.message.edit_text(
        f"📨 <b>Taklif yuborish</b>\n\n"
        f"📍 Hudud: <b>{region_name}</b>\n"
        f"Guruhda hozir {group_member_count}/{MAX_MEMBERS} ta xonadon bor.\n"
        f"Qaysi xonadonga taklif yuborasiz?",
        reply_markup=house_list_keyboard(candidates, "diplo:inv_send", back_to="diplo:group_menu"),
        parse_mode="HTML"
    )


@router.callback_query(DiploState.selecting_invite_target, F.data.startswith("diplo:inv_send:"))
async def group_invite_send(callback: CallbackQuery, state: FSMContext):
    target_house_id = int(callback.data.split(":")[2])
    data = await state.get_data()
    group_id = data["group_id"]
    my_house_id = data["my_house_id"]

    async with AsyncSessionFactory() as session:
        group_repo = AllianceGroupRepo(session)
        house_repo = HouseRepo(session)

        existing_invite = await group_repo.get_pending_invite(group_id, target_house_id)
        if existing_invite:
            await callback.answer("❌ Bu xonadonga allaqachon taklif yuborilgan.", show_alert=True)
            await state.clear()
            return

        group = await group_repo.get_group_by_id(group_id)
        if not group or len(group.members) >= MAX_MEMBERS:
            await callback.answer(f"❌ Guruhda joy qolmadi ({MAX_MEMBERS} ta limit).", show_alert=True)
            await state.clear()
            return

        other_group = await group_repo.get_house_active_group(target_house_id)
        if other_group:
            await callback.answer("❌ Bu xonadon allaqachon boshqa ittifoq guruhida.", show_alert=True)
            await state.clear()
            return

        target_house = await house_repo.get_by_id(target_house_id)
        my_house = await house_repo.get_by_id(my_house_id)

        # Region tekshiruvi
        if target_house and my_house and target_house.region != my_house.region:
            await callback.answer(
                f"❌ Faqat bir hududdagi xonadonlar ittifoq tuzishi mumkin!\n"
                f"Sizning hududingiz: {my_house.region.value}\n"
                f"Maqsad hududi: {target_house.region.value}",
                show_alert=True
            )
            await state.clear()
            return
        invite = await group_repo.send_invite(group_id, my_house_id, target_house_id)

        group_name = group.name
        member_count = len(group.members)
        target_lord_id = target_house.lord_id if target_house else None

    if target_lord_id:
        try:
            await callback.bot.send_message(
                target_lord_id,
                f"📨 <b>ITTIFOQ TAKLIFI!</b>\n\n"
                f"<b>{my_house.name}</b> xonadoni sizni\n"
                f"<b>«{group_name}»</b> ittifoq guruhiga taklif qilmoqda.\n\n"
                f"Guruhda hozir {member_count}/{MAX_MEMBERS} ta xonadon.",
                reply_markup=alliance_invite_keyboard(invite.id),
                parse_mode="HTML"
            )
        except Exception:
            await callback.answer("❌ Lordiga xabar yuborib bo'lmadi.", show_alert=True)
            await state.clear()
            return

    await state.clear()
    await callback.answer()
    await callback.message.edit_text(
        f"✅ <b>{target_house.name}</b> xonadoniga taklif yuborildi.",
        reply_markup=back_only_keyboard("diplo:group_menu"),
        parse_mode="HTML"
    )


# ─── TAKLIF QABUL / RAD ───────────────────────────────────────────────────

@router.callback_query(F.data.startswith("diplo:inv_accept:"))
async def invite_accept(callback: CallbackQuery):
    invite_id = int(callback.data.split(":")[2])

    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        group_repo = AllianceGroupRepo(session)
        house_repo = HouseRepo(session)

        user = await user_repo.get_by_id(callback.from_user.id)
        if not user or not user.house_id:
            await callback.answer("❌ Xonadoningiz yo'q.", show_alert=True)
            return

        existing = await group_repo.get_house_active_group(user.house_id)
        if existing:
            await callback.answer("❌ Siz allaqachon boshqa ittifoq guruhidasiz.", show_alert=True)
            return

        invite = await group_repo.get_invite_by_id(invite_id)
        if not invite or invite.status != "pending":
            await callback.answer("❌ Bu taklif endi amal qilmaydi.", show_alert=True)
            return
        if invite.to_house_id != user.house_id:
            await callback.answer("❌ Bu taklif sizga emas.", show_alert=True)
            return

        # Region tekshiruvi: taklif yuborgan va qabul qiluvchi bir hududda bo'lishi shart
        my_house_check = await house_repo.get_by_id(user.house_id)
        leader_house_check = await house_repo.get_by_id(invite.group.leader_house_id)
        if my_house_check and leader_house_check and my_house_check.region != leader_house_check.region:
            await callback.answer(
                f"❌ Faqat bir hududdagi xonadonlar ittifoq tuzishi mumkin!\n"
                f"Sizning hududingiz: {my_house_check.region.value}\n"
                f"Guruh hududi: {leader_house_check.region.value}",
                show_alert=True
            )
            return

        success = await group_repo.accept_invite(invite_id)
        if not success:
            await callback.answer(
                f"❌ Guruhda joy qolmadi ({MAX_MEMBERS} ta limit).",
                show_alert=True
            )
            return

        group = await group_repo.get_group_by_id(invite.group_id)
        my_house = await house_repo.get_by_id(user.house_id)
        leader_house = await house_repo.get_by_id(group.leader_house_id)
        group_name = group.name
        member_count = len(group.members)
        leader_lord_id = leader_house.lord_id if leader_house else None

    if leader_lord_id:
        try:
            await callback.bot.send_message(
                leader_lord_id,
                f"✅ <b>{my_house.name}</b> xonadoni\n"
                f"<b>«{group_name}»</b> guruhiga qo'shildi!\n"
                f"Guruhda hozir {member_count}/{MAX_MEMBERS} ta xonadon.",
                parse_mode="HTML"
            )
        except Exception:
            pass

    await callback.answer()
    await callback.message.edit_text(
        f"✅ <b>«{group_name}»</b> ittifoq guruhiga qo'shildingiz!\n\n"
        f"Guruhda hozir {member_count}/{MAX_MEMBERS} ta xonadon.",
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("diplo:inv_reject:"))
async def invite_reject(callback: CallbackQuery):
    invite_id = int(callback.data.split(":")[2])

    async with AsyncSessionFactory() as session:
        group_repo = AllianceGroupRepo(session)
        house_repo = HouseRepo(session)

        invite = await group_repo.get_invite_by_id(invite_id)
        if not invite or invite.status != "pending":
            await callback.answer("❌ Bu taklif endi amal qilmaydi.", show_alert=True)
            return

        await group_repo.reject_invite(invite_id)
        group = await group_repo.get_group_by_id(invite.group_id)
        to_house = await house_repo.get_by_id(invite.to_house_id)
        leader_house = await house_repo.get_by_id(group.leader_house_id)
        group_name = group.name
        to_house_name = to_house.name if to_house else "Noma'lum"
        leader_lord_id = leader_house.lord_id if leader_house else None

    if leader_lord_id:
        try:
            await callback.bot.send_message(
                leader_lord_id,
                f"❌ <b>{to_house_name}</b> xonadoni\n"
                f"<b>«{group_name}»</b> guruhiga qo'shilishni rad etdi.",
                parse_mode="HTML"
            )
        except Exception:
            pass

    await callback.answer()
    await callback.message.edit_text(
        f"❌ <b>«{group_name}»</b> guruhining taklifi rad etildi.",
        parse_mode="HTML"
    )


# ─── GURUH MA'LUMOTLARI ─────────────────────────────────────────────────────

@router.callback_query(F.data == "diplo:group_info")
async def group_info(callback: CallbackQuery):
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)
        if not user or not user.house_id:
            await callback.answer("❌ Xonadoningiz yo'q.", show_alert=True)
            return

        group_repo = AllianceGroupRepo(session)
        group = await group_repo.get_house_active_group(user.house_id)
        if not group:
            await callback.answer("❌ Siz ittifoq guruhida emassiz.", show_alert=True)
            return

        is_leader = group.leader_house_id == user.house_id
        lines = [f"🏰 <b>«{group.name}»</b>\n"]
        total_power = 0
        for m in group.members:
            h = m.house
            power = h.total_soldiers + h.total_dragons * 200 + h.total_scorpions * 25
            total_power += power
            role_icon = "👑" if h.id == group.leader_house_id else "⚔️"
            lines.append(
                f"{role_icon} <b>{h.name}</b>\n"
                f"   ⚡ {power:,}  |  🗡️ {h.total_soldiers:,}  🐉 {h.total_dragons}  🏹 {h.total_scorpions}"
            )
        lines.append(f"\n📊 Umumiy kuch: <b>{total_power:,}</b>")
        lines.append(f"👥 A'zolar: {len(group.members)}/{MAX_MEMBERS}")

    await callback.answer()
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=alliance_group_menu_keyboard(in_group=True, is_leader=is_leader),
        parse_mode="HTML"
    )


# ─── NOM O'ZGARTIRISH ─────────────────────────────────────────────────────

@router.callback_query(F.data == "diplo:group_rename")
async def group_rename_start(callback: CallbackQuery, state: FSMContext):
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)
        if not user or not user.house_id:
            await callback.answer("❌ Xonadoningiz yo'q.", show_alert=True)
            return

        group_repo = AllianceGroupRepo(session)
        group = await group_repo.get_house_active_group(user.house_id)
        if not group or group.leader_house_id != user.house_id:
            await callback.answer("❌ Faqat tashkilotchi nom o'zgartira oladi.", show_alert=True)
            return
        group_id = group.id
        group_name = group.name

    await state.set_state(DiploState.entering_new_name)
    await state.update_data(group_id=group_id)
    await callback.answer()
    await callback.message.edit_text(
        f"✏️ <b>Yangi nom kiriting:</b>\n\nHozirgi nom: <b>{group_name}</b>",
        parse_mode="HTML"
    )


@router.message(DiploState.entering_new_name)
async def group_rename_execute(message: Message, state: FSMContext):
    new_name = message.text.strip()
    if len(new_name) < 2 or len(new_name) > 40:
        await message.answer("❌ Nom 2 dan 40 gacha belgi bo'lishi kerak. Qaytadan kiriting:")
        return

    data = await state.get_data()
    async with AsyncSessionFactory() as session:
        group_repo = AllianceGroupRepo(session)
        await group_repo.rename_group(data["group_id"], new_name)

    await state.clear()
    await message.answer(
        f"✅ Ittifoq nomi <b>«{new_name}»</b> ga o'zgartirildi.",
        parse_mode="HTML",
        reply_markup=alliance_group_menu_keyboard(in_group=True, is_leader=True)
    )


# ─── GURUHNI TARQATISH ─────────────────────────────────────────────────────

@router.callback_query(F.data == "diplo:group_disband")
async def group_disband_confirm(callback: CallbackQuery):
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)
        if not user or not user.house_id:
            await callback.answer("❌ Xonadoningiz yo'q.", show_alert=True)
            return

        group_repo = AllianceGroupRepo(session)
        group = await group_repo.get_house_active_group(user.house_id)
        if not group or group.leader_house_id != user.house_id:
            await callback.answer("❌ Faqat tashkilotchi guruhni tarqata oladi.", show_alert=True)
            return
        group_id = group.id
        group_name = group.name

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⚠️ HA, TARQAT!", callback_data=f"diplo:disband_ok:{group_id}"),
        InlineKeyboardButton(text="❌ Bekor", callback_data="diplo:group_menu"),
    ]])
    await callback.answer()
    await callback.message.edit_text(
        f"⚠️ <b>«{group_name}»</b> guruhini tarqatmoqchimisiz?\n\n"
        f"Barcha a'zolar guruhdan chiqariladi.",
        reply_markup=kb,
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("diplo:disband_ok:"))
async def group_disband_execute(callback: CallbackQuery):
    group_id = int(callback.data.split(":")[2])

    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)

        group_repo = AllianceGroupRepo(session)
        group = await group_repo.get_group_by_id(group_id)
        if not group or group.leader_house_id != user.house_id:
            await callback.answer("❌ Ruxsat yo'q.", show_alert=True)
            return

        group_name = group.name
        lord_ids = []
        for m in group.members:
            if m.house_id != user.house_id:
                h = await house_repo.get_by_id(m.house_id)
                if h and h.lord_id:
                    lord_ids.append(h.lord_id)

        await group_repo.disband_group(group_id)

    for lord_id in lord_ids:
        try:
            await callback.bot.send_message(
                lord_id,
                f"💔 <b>«{group_name}»</b> ittifoq guruhi tashkilotchi tomonidan tarqatildi.",
                parse_mode="HTML"
            )
        except Exception:
            pass

    await callback.answer()
    await callback.message.edit_text(
        f"💔 <b>«{group_name}»</b> ittifoq guruhi tarqatildi.",
        reply_markup=back_only_keyboard("diplo:group_menu"),
        parse_mode="HTML"
    )


# ─── GURUHDAN CHIQISH ──────────────────────────────────────────────────────

@router.callback_query(F.data == "diplo:group_leave")
async def group_leave_confirm(callback: CallbackQuery):
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)
        if not user or not user.house_id:
            await callback.answer("❌ Xonadoningiz yo'q.", show_alert=True)
            return

        group_repo = AllianceGroupRepo(session)
        group = await group_repo.get_house_active_group(user.house_id)
        if not group:
            await callback.answer("❌ Siz ittifoq guruhida emassiz.", show_alert=True)
            return
        if group.leader_house_id == user.house_id:
            await callback.answer(
                "❌ Tashkilotchi guruhdan chiqolmaydi. Avval guruhni tarqating.",
                show_alert=True
            )
            return
        group_id = group.id
        group_name = group.name

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🚪 HA, CHIQISH", callback_data=f"diplo:leave_ok:{group_id}"),
        InlineKeyboardButton(text="❌ Bekor", callback_data="diplo:group_menu"),
    ]])
    await callback.answer()
    await callback.message.edit_text(
        f"🚪 <b>«{group_name}»</b> guruhidan chiqmoqchimisiz?",
        reply_markup=kb,
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("diplo:leave_ok:"))
async def group_leave_execute(callback: CallbackQuery):
    group_id = int(callback.data.split(":")[2])

    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)
        user = await user_repo.get_by_id(callback.from_user.id)

        group_repo = AllianceGroupRepo(session)
        group = await group_repo.get_group_by_id(group_id)
        if not group:
            await callback.answer("❌ Guruh topilmadi.", show_alert=True)
            return

        group_name = group.name
        my_house = await house_repo.get_by_id(user.house_id)
        leader_house = await house_repo.get_by_id(group.leader_house_id)
        leader_lord_id = leader_house.lord_id if leader_house else None
        my_house_name = my_house.name if my_house else "Noma'lum"

        await group_repo.leave_group(group_id, user.house_id)

    if leader_lord_id:
        try:
            await callback.bot.send_message(
                leader_lord_id,
                f"🚪 <b>{my_house_name}</b> xonadoni\n"
                f"<b>«{group_name}»</b> guruhidan chiqib ketdi.",
                parse_mode="HTML"
            )
        except Exception:
            pass

    await callback.answer()
    await callback.message.edit_text(
        f"🚪 <b>«{group_name}»</b> guruhidan chiqdingiz.",
        reply_markup=back_only_keyboard("diplo:group_menu"),
        parse_mode="HTML"
    )
