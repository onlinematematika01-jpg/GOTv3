from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from database.engine import AsyncSessionFactory
from database.repositories import UserRepo, HouseRepo, CustomItemRepo
from database.models import RoleEnum
from keyboards import main_menu_keyboard

router = Router()

ROLE_LABELS = {
    RoleEnum.ADMIN: "🦅 Uch Ko'zli Qarg'a",
    RoleEnum.HIGH_LORD: "👑 Hukmdor (Oliy Lord)",
    RoleEnum.LORD: "🏰 Vassal Lordi",
    RoleEnum.MEMBER: "⚔️ A'zo",
}


@router.message(F.text == "👤 Profil")
@router.message(Command("profile"))
async def show_profile(message: Message):
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        custom_repo = CustomItemRepo(session)
        from database.repositories import IronBankRepo
        iron_bank_repo = IronBankRepo(session)

        user = await user_repo.get_by_id(message.from_user.id)

        if not user:
            await message.answer("❌ Siz ro'yxatdan o'tmagansiz. /start bosing.")
            return

        house_name = user.house.name if user.house else "—"
        region = user.region.value if user.region else "—"
        role_label = ROLE_LABELS.get(user.role, user.role.value)

        # Xonadon ma'lumotlari (har doim joriy xonadondan)
        if user.house:
            treasury  = user.house.treasury
            soldiers  = user.house.total_soldiers
            dragons   = user.house.total_dragons
            scorpions = user.house.total_scorpions
            house_debt = await iron_bank_repo.get_house_active_debt(user.house_id)
        else:
            treasury = soldiers = dragons = scorpions = house_debt = 0

        # Custom itemlar (xonadon itemlari)
        house_items = await custom_repo.get_house_items_with_info(user.house_id) if user.house_id else []
        custom_items_text = ""
        if house_items:
            parts = [f"{r.item.emoji} {r.item.name}: {r.quantity} ta" for r in house_items]
            custom_items_text = "\n🎒 <b>Maxsus qurollar:</b>\n  " + "\n  ".join(parts) + "\n"

        text = (
            f"👤 <b>{user.full_name}</b>\n"
            f"{'@' + user.username if user.username else ''}\n\n"
            f"👑 <b>Rol:</b> {role_label}\n"
            f"🏰 <b>Xonadon:</b> {house_name}\n"
            f"🗺️ <b>Hudud:</b> {region}\n\n"
            f"💰 <b>Xazina:</b> {treasury:,} tanga\n"
            f"🗡️ <b>Askarlar:</b> {soldiers:,}\n"
            f"🐉 <b>Ajdarlar:</b> {dragons}\n"
            f"🏹 <b>Skorpionlar:</b> {scorpions}\n"
            f"{custom_items_text}\n"
            f"🏦 <b>Xonadon qarzi:</b> {house_debt:,} tanga\n"
            f"{'⚠️ <b>SURGUN QILINGAN</b>' if user.is_exiled else ''}"
        )

        await message.answer(text, parse_mode="HTML")


@router.message(F.text == "🏰 Xonadon")
@router.message(Command("house"))
async def show_house(message: Message):
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)
        custom_repo = CustomItemRepo(session)
        user = await user_repo.get_by_id(message.from_user.id)

        if not user or not user.house_id:
            await message.answer("❌ Siz hech bir xonadonga tegishli emassiz.")
            return

        house = await house_repo.get_by_id(user.house_id)
        if not house:
            await message.answer("❌ Xonadon topilmadi.")
            return

        members = await user_repo.get_house_members(house.id)
        member_count = len(members)

        lord = await user_repo.get_by_id(house.lord_id) if house.lord_id else None
        high_lord = await user_repo.get_by_id(house.high_lord_id) if house.high_lord_id else None

        members_text = "\n".join(
            f"  {'👑' if m.role == RoleEnum.LORD else '⚔️'} {m.full_name}"
            for m in members[:10]
        )

        # Xonadonning custom itemlarini olish
        house_items = await custom_repo.get_house_items_with_info(house.id)
        custom_items_text = ""
        if house_items:
            parts = [f"{r.item.emoji} {r.item.name}: {r.quantity} ta" for r in house_items]
            custom_items_text = "\n🎯 <b>Maxsus qurollar:</b>\n  " + "\n  ".join(parts) + "\n"

        # Xonadon qarzi
        from database.repositories import IronBankRepo
        iron_bank_repo = IronBankRepo(session)
        house_debt = await iron_bank_repo.get_house_active_debt(house.id)
        debt_text = f"\n🏦 <b>Xonadon qarzi:</b> {house_debt:,} tanga" if house_debt > 0 else ""

        occ_text = ""
        if house.is_under_occupation:
            occ_text = f"\n⛓️ <b>Bosib olingan!</b> Soliq: {house.permanent_tax_rate*100:.0f}%"

        text = (
            f"🏰 <b>{house.name}</b>\n"
            f"🗺️ Hudud: {house.region.value}\n\n"
            f"👑 Lord: {lord.full_name if lord else '—'}\n"
            f"🦅 Hukmdor: {high_lord.full_name if high_lord else '—'}\n\n"
            f"💰 Xazina: {house.treasury:,} tanga\n"
            f"🗡️ Askarlar: {house.total_soldiers:,}\n"
            f"🐉 Ajdarlar: {house.total_dragons}\n"
            f"🏹 Skorpionlar: {house.total_scorpions}\n"
            f"{custom_items_text}"
            f"{debt_text}\n\n"
            f"👥 A'zolar ({member_count}/10):\n{members_text}"
            f"{occ_text}"
        )

        await message.answer(text, parse_mode="HTML")
