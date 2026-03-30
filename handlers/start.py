from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart, Command
from database.engine import AsyncSessionFactory
from database.repositories import UserRepo, HouseRepo, ChronicleRepo
from database.models import RoleEnum
from keyboards import main_menu_keyboard
from utils.chronicle import post_to_chronicle, format_chronicle
import logging

router = Router()
logger = logging.getLogger(__name__)

ADMIN_IDS = []  # .env dan yoki settings dan to'ldiring


@router.message(CommandStart())
async def cmd_start(message: Message):
    user_tg = message.from_user
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)

        # Foydalanuvchi mavjudmi?
        user = await user_repo.get_by_id(user_tg.id)
        if user:
            treasury = user.house.treasury if user.house else 0
            await message.answer(
                f"🐺 <b>Xush kelibsiz, {user.full_name}!</b>\n\n"
                f"🏰 Xonadon: {user.house.name if user.house else 'Yo\'q'}\n"
                f"👑 Rol: {user.role.value}\n"
                f"💰 Xonadon xazinasi: {treasury:,} tanga",
                reply_markup=main_menu_keyboard(user.role),
                parse_mode="HTML"
            )
            return

        # Referal tekshiruvi
        referral_by = None
        args = message.text.split()
        if len(args) > 1:
            try:
                ref_id = int(args[1])
                ref_user = await user_repo.get_by_id(ref_id)
                if ref_user and ref_user.house_id:
                    referral_by = ref_id
                    # Referal bonusi — xonadon xazinasiga
                    ref_count = await user_repo.get_referral_count_today(ref_id)
                    from config.settings import settings
                    if ref_count < settings.MAX_REFERRAL_PER_DAY:
                        await house_repo.update_treasury(ref_user.house_id, settings.REFERRAL_BONUS)
            except (ValueError, TypeError):
                pass

        # Admin tekshiruvi
        if user_tg.id in ADMIN_IDS:
            user = await user_repo.create(user_tg.id, user_tg.full_name, user_tg.username)
            from sqlalchemy import update
            from database.models import User
            await session.execute(
                update(User).where(User.id == user_tg.id).values(role=RoleEnum.ADMIN)
            )
            await session.commit()
            await message.answer(
                "🦅 <b>Uch Ko'zli Qarg'a sifatida tizimga kirdingiz!</b>",
                reply_markup=main_menu_keyboard(RoleEnum.ADMIN),
                parse_mode="HTML"
            )
            return

        # Yangi foydalanuvchi — xonadon topish
        result = await user_repo.find_available_house()
        if result is None:
            await message.answer("❌ Hozirda bo'sh joy yo'q. Keyinroq urinib ko'ring.")
            return

        house, assign_role = result

        if house is None:
            await message.answer("❌ Xonadon topilmadi. Admin bilan bog'laning.")
            return

        # Foydalanuvchi yaratish
        user = await user_repo.create(user_tg.id, user_tg.full_name, user_tg.username)
        if referral_by:
            from sqlalchemy import update
            from database.models import User
            await session.execute(
                update(User).where(User.id == user_tg.id).values(referral_by=referral_by)
            )
            await session.commit()

        role = RoleEnum.LORD if assign_role == "lord" else RoleEnum.MEMBER
        await user_repo.assign_to_house(user, house, role)

        role_text = "Vassal Lordi 👑" if role == RoleEnum.LORD else "A'zo ⚔️"
        await message.answer(
            f"🐺 <b>Yetti Qirollikka xush kelibsiz, {user_tg.full_name}!</b>\n\n"
            f"🏰 <b>Xonadon:</b> {house.name}\n"
            f"🗺️ <b>Hudud:</b> {house.region.value}\n"
            f"👑 <b>Sizning rolingiz:</b> {role_text}\n\n"
            f"💰 Xonadon xazinasi: {house.treasury:,} tanga\n"
            f"📜 /help — qo'llanma",
            reply_markup=main_menu_keyboard(role),
            parse_mode="HTML"
        )

        logger.info(f"Yangi foydalanuvchi: {user_tg.full_name} → {house.name} ({role.value})")


@router.message(Command("help"))
async def cmd_help(message: Message):
    text = (
        "📜 <b>Game of Thrones Bot V3 — Qo'llanma</b>\n\n"
        "🗺️ <b>Hududlar:</b> 9 ta hudud, har birida xonadon bor\n\n"
        "👑 <b>Rollar:</b>\n"
        "• Uch Ko'zli Qarg'a (Admin) — cheksiz vakolat\n"
        "• Hukmdor (Oliy Lord) — hududning rahbari\n"
        "• Lord — 10 kishilik xonadon sardori\n"
        "• A'zo — jangchi/fermer\n\n"
        "💰 <b>Iqtisod (xonadon xazinasi tizimi):</b>\n"
        "• Kunlik farm: Lord +50, A'zo +20 → xonadon xazinasiga\n"
        "• Referal bonus xonadon xazinasiga tushadi\n"
        "• O'lpon: Vassal → Hukmdor xazinasiga 100 tanga/kun\n"
        "• Xarid faqat Lord tomonidan xazinadan amalga oshiriladi\n\n"
        "⚔️ <b>Urush:</b> 19:00 — 23:00 orasida\n"
        "🛒 <b>Bozor:</b> Askar (1), Ajdar (150), Skorpion (25)\n"
        "🏦 <b>Temir Bank:</b> Qarz xazinaga tushadi, xazinadan to'lanadi\n"
        "💬 <b>Ichki Chat:</b> Xonadon a'zolari bilan muloqot\n"
        "🤝 <b>Diplomatiya:</b> Ittifoq tuzish/buzish\n\n"
        "📊 /profile — profilingiz\n"
        "🏰 /house — xonadon ma'lumotlari"
    )
    await message.answer(text, parse_mode="HTML")
