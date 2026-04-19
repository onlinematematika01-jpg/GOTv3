from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart, Command
from database.engine import AsyncSessionFactory
from database.repositories import UserRepo, HouseRepo, ChronicleRepo
from database.models import RoleEnum
from keyboards import main_menu_keyboard
from config.settings import settings
from utils.chronicle import post_to_chronicle, format_chronicle
import logging

router = Router()
logger = logging.getLogger(__name__)


@router.message(CommandStart())
async def cmd_start(message: Message):
    user_tg = message.from_user
    args = message.text.split()

    async with AsyncSessionFactory() as session:
        user_repo  = UserRepo(session)
        house_repo = HouseRepo(session)

        # Mavjud foydalanuvchi
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

        # ── Referal link tekshiruvi ──────────────────────────────
        # Format: /start house_HOUSEID_LORDID  (xonadon taklifi)
        # Format: /start USERID               (oddiy referal)
        invite_house_id = None
        referral_by     = None

        if len(args) > 1:
            param = args[1]

            # Xonadon taklifi: house_37_123456789
            if param.startswith("house_"):
                parts = param.split("_")
                if len(parts) == 3:
                    try:
                        h_id  = int(parts[1])
                        l_id  = int(parts[2])
                        house = await house_repo.get_by_id(h_id)
                        lord  = await user_repo.get_by_id(l_id)
                        # Lord hali ham shu xonadondami?
                        if house and lord and lord.house_id == h_id:
                            # Bo'sh joy bormi?
                            from sqlalchemy import select, func
                            from database.models import User as UserModel
                            cnt_res = await session.execute(
                                select(func.count(UserModel.id))
                                .where(UserModel.house_id == h_id, UserModel.is_active == True)
                            )
                            cnt = cnt_res.scalar() or 0
                            if cnt < settings.MAX_HOUSE_MEMBERS:
                                invite_house_id = h_id
                                referral_by     = l_id
                    except (ValueError, TypeError):
                        pass

            # Oddiy referal: faqat user_id
            else:
                try:
                    ref_id   = int(param)
                    ref_user = await user_repo.get_by_id(ref_id)
                    if ref_user and ref_user.house_id:
                        referral_by = ref_id
                except (ValueError, TypeError):
                    pass

        # ── Admin tekshiruvi ─────────────────────────────────────
        if user_tg.id in settings.ADMIN_IDS:
            user = await user_repo.create(user_tg.id, user_tg.full_name, user_tg.username)
            from sqlalchemy import update
            from database.models import User
            await session.execute(
                update(User).where(User.id == user_tg.id).values(role=RoleEnum.ADMIN)
            )
            await session.commit()
            await message.answer(
                "🦅 <b>Uch Ko\'zli Qarg\'a sifatida tizimga kirdingiz!</b>",
                reply_markup=main_menu_keyboard(RoleEnum.ADMIN),
                parse_mode="HTML"
            )
            return

        # ── Xonadon tanlash ─────────────────────────────────────
        if invite_house_id:
            # Taklif linki orqali — aynan shu xonadonga
            house       = await house_repo.get_by_id(invite_house_id)
            assign_role = "member"
        else:
            # Oddiy qo'shilish — bo'sh xonadon topish
            result = await user_repo.find_available_house()
            if result is None or result[0] is None:
                await message.answer("❌ Hozirda bo\'sh joy yo\'q. Keyinroq urinib ko\'ring.")
                return
            house, assign_role = result

        # ── Foydalanuvchi yaratish ───────────────────────────────
        user = await user_repo.create(user_tg.id, user_tg.full_name, user_tg.username)

        if referral_by:
            from sqlalchemy import update
            from database.models import User
            await session.execute(
                update(User).where(User.id == user_tg.id).values(referral_by=referral_by)
            )
            # Referal bonusi — cheklov bilan
            ref_user  = await user_repo.get_by_id(referral_by)
            ref_count = await user_repo.get_referral_count_today(referral_by)
            if ref_user and ref_user.house_id and ref_count < settings.MAX_REFERRAL_PER_DAY:
                await house_repo.update_treasury(ref_user.house_id, settings.REFERRAL_BONUS)

        role = RoleEnum.LORD if assign_role == "lord" else RoleEnum.MEMBER
        await user_repo.assign_to_house(user, house, role)

        invite_note = ""
        if invite_house_id:
            invite_note = f"\n🔗 <i>Taklif linki orqali qo\'shildingiz.</i>"

        role_text = "Vassal Lordi 👑" if role == RoleEnum.LORD else "A\'zo ⚔️"
        await message.answer(
            f"🐺 <b>Yetti Qirollikka xush kelibsiz, {user_tg.full_name}!</b>\n\n"
            f"🏰 <b>Xonadon:</b> {house.name}\n"
            f"🗺️ <b>Hudud:</b> {house.region.value}\n"
            f"👑 <b>Sizning rolingiz:</b> {role_text}"
            f"{invite_note}\n\n"
            f"💰 Xonadon xazinasi: {house.treasury:,} tanga\n"
            f"📜 /help — qo\'llanma",
            reply_markup=main_menu_keyboard(role),
            parse_mode="HTML"
        )

        logger.info(
            f"Yangi foydalanuvchi: {user_tg.full_name} → {house.name} "
            f"({'taklif' if invite_house_id else 'auto'})"
        )


@router.message(Command("help"))
async def cmd_help(message: Message):
    text = (
        "📜 <b>Game of Thrones Bot V3 — Qo\'llanma</b>\n\n"
        "🗺️ <b>Hududlar:</b> 9 ta hudud, har birida xonadon bor\n\n"
        "👑 <b>Rollar:</b>\n"
        "• Uch Ko\'zli Qarg\'a (Admin) — cheksiz vakolat\n"
        "• Hukmdor (Oliy Lord) — hududning rahbari\n"
        "• Lord — 10 kishilik xonadon sardori\n"
        "• Ritsar — xonadon jangchisi\n"
        "• A\'zo — fermer/jangchi\n\n"
        "💰 <b>Iqtisod:</b>\n"
        "• Kunlik farm → xonadon xazinasiga\n"
        "• Referal bonus xonadon xazinasiga tushadi\n"
        "• O\'lpon: Vassal → Hukmdor xazinasiga\n\n"
        "⚔️ <b>Urush:</b> belgilangan vaqtda\n"
        "🛒 <b>Bozor:</b> Askar, Ajdar, Skorpion\n"
        "🏦 <b>Temir Bank:</b> Qarz va omonat\n"
        "🤝 <b>Diplomatiya:</b> Ittifoq tuzish\n\n"
        "📊 /profile — profil\n"
        "🏰 /house — xonadon"
    )
    await message.answer(text, parse_mode="HTML")


@router.message(Command("invite"))
async def cmd_invite(message: Message):
    """Lord o'z xonadoniga taklif linki oladi"""
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        user = await user_repo.get_by_id(message.from_user.id)

        if not user or user.role not in [RoleEnum.LORD, RoleEnum.HIGH_LORD, RoleEnum.ADMIN]:
            await message.answer("❌ Faqat Lordlar taklif linki olishi mumkin.")
            return

        if not user.house_id:
            await message.answer("❌ Xonadoningiz yo\'q.")
            return

        bot_info = await message.bot.get_me()
        link = (
            f"https://t.me/{bot_info.username}"
            f"?start=house_{user.house_id}_{user.id}"
        )

        from database.repositories import HouseRepo as HR
        house_repo = HR(session)
        house = await house_repo.get_by_id(user.house_id)

        from sqlalchemy import select, func
        from database.models import User as UserModel
        cnt_res = await session.execute(
            select(func.count(UserModel.id))
            .where(UserModel.house_id == user.house_id, UserModel.is_active == True)
        )
        cnt = cnt_res.scalar() or 0
        bo_sh = settings.MAX_HOUSE_MEMBERS - cnt

        await message.answer(
            f"🔗 <b>{house.name} — Taklif linki</b>\n\n"
            f"Bu link orqali qo\'shilgan kishi aynan sizning "
            f"xonadoningizga tushadi:\n\n"
            f"<code>{link}</code>\n\n"
            f"👥 Hozirgi a\'zolar: {cnt}/{settings.MAX_HOUSE_MEMBERS}\n"
            f"🟢 Bo\'sh joylar: {bo_sh}",
            parse_mode="HTML"
        )


@router.message(F.text == "🔗 Taklif Linki")
async def invite_button(message: Message):
    """Tugma orqali taklif linki"""
    await cmd_invite(message)
