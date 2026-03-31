import logging
import re

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config.settings import settings
from database.engine import async_session_maker
from database.repositories import (
    HouseRepo, UserRepo, MarketRepo,
    BotSettingsRepo, FarmScheduleRepo
)
from database.models import UserRole

logger = logging.getLogger(__name__)
router = Router()


# ═══════════════════════════════════════════════════════════════════════════════
# STATES
# ═══════════════════════════════════════════════════════════════════════════════

class AdminState(StatesGroup):
    # Give gold
    waiting_house_id    = State()
    waiting_gold_amount = State()

    # Market price
    waiting_item_type  = State()
    waiting_item_price = State()

    # Bot settings
    waiting_setting_key   = State()
    waiting_setting_value = State()


class FarmScheduleState(StatesGroup):
    waiting_input  = State()   # "HH:MM MIQDOR" kiritish
    waiting_edit   = State()   # mavjud farm miqdorini tahrirlash


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def is_admin(user_id: int) -> bool:
    return user_id in settings.ADMIN_IDS


def parse_farm_input(text: str) -> tuple[int, int, int] | None:
    """
    '08:00 50'  yoki  '8:0 50' formatini parse qiladi.
    Muvaffaqiyatli bo'lsa (hour, minute, amount) qaytaradi, aks holda None.
    """
    pattern = r"^(\d{1,2}):(\d{1,2})\s+(\d+)$"
    match = re.match(pattern, text.strip())
    if not match:
        return None
    hour, minute, amount = int(match[1]), int(match[2]), int(match[3])
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 1 <= amount <= 1_000_000):
        return None
    return hour, minute, amount


async def build_farm_keyboard(session) -> InlineKeyboardMarkup:
    """Joriy farm jadvalini inline keyboard ko'rinishida qaytaradi."""
    repo = FarmScheduleRepo(session)
    schedules = await repo.get_all()

    builder = InlineKeyboardBuilder()
    for s in schedules:
        status_icon = "✅" if s.is_active else "❌"
        builder.button(
            text=f"{status_icon} {s.time_str()} — {s.amount} 🪙",
            callback_data=f"farm_info:{s.id}",
        )
    builder.button(text="➕ Yangi farm qo'shish", callback_data="farm_add")
    if schedules:
        builder.button(text="🗑 Barchasini tozalash", callback_data="farm_clear_confirm")
    builder.button(text="🔙 Admin menyu", callback_data="admin_menu")
    builder.adjust(1)
    return builder.as_markup()


async def build_farm_item_keyboard(schedule_id: int) -> InlineKeyboardMarkup:
    """Bitta farm uchun amallar tugmalarini qaytaradi."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Faol/Nofaol", callback_data=f"farm_toggle:{schedule_id}")
    builder.button(text="✏️ Miqdorni tahrirlash", callback_data=f"farm_edit:{schedule_id}")
    builder.button(text="🗑 O'chirish", callback_data=f"farm_delete:{schedule_id}")
    builder.button(text="🔙 Orqaga", callback_data="admin_farm_menu")
    builder.adjust(2)
    return builder.as_markup()


async def get_farm_list_text(session) -> str:
    """Farm jadvali matnini qaytaradi."""
    repo = FarmScheduleRepo(session)
    schedules = await repo.get_all()

    if not schedules:
        return (
            "📋 <b>Kunlik Farm Jadvali</b>\n\n"
            "Hozircha hech qanday farm belgilanmagan.\n"
            "➕ Yangi farm qo'shish uchun tugmani bosing."
        )

    lines = ["📋 <b>Kunlik Farm Jadvali:</b>\n"]
    for s in schedules:
        status = "✅ Faol" if s.is_active else "❌ Nofaol"
        lines.append(f"• <b>{s.time_str()}</b> — <b>{s.amount} 🪙</b>  [{status}]")

    active_count = sum(1 for s in schedules if s.is_active)
    lines.append(f"\nJami: {len(schedules)} ta ({active_count} ta faol)")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# ADMIN PANEL — BOSH MENYU
# ═══════════════════════════════════════════════════════════════════════════════

@router.message(Command("admin"))
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Sizda admin huquqi yo'q.")
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="🌾 Farm Sozlamalari",  callback_data="admin_farm_menu")
    builder.button(text="💰 Oltin berish",       callback_data="admin_give_gold")
    builder.button(text="🛒 Bozor narxlari",     callback_data="admin_market")
    builder.button(text="⚙️ Bot sozlamalari",    callback_data="admin_settings")
    builder.button(text="📊 Statistika",         callback_data="admin_stats")
    builder.adjust(2)

    await message.answer(
        "🦅 <b>Admin Panel</b>\n\nQuyidagi bo'limlardan birini tanlang:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_menu")
async def admin_menu_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="🌾 Farm Sozlamalari",  callback_data="admin_farm_menu")
    builder.button(text="💰 Oltin berish",       callback_data="admin_give_gold")
    builder.button(text="🛒 Bozor narxlari",     callback_data="admin_market")
    builder.button(text="⚙️ Bot sozlamalari",    callback_data="admin_settings")
    builder.button(text="📊 Statistika",         callback_data="admin_stats")
    builder.adjust(2)

    await callback.message.edit_text(
        "🦅 <b>Admin Panel</b>\n\nQuyidagi bo'limlardan birini tanlang:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


# ═══════════════════════════════════════════════════════════════════════════════
# FARM BOSHQARUVI
# ═══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "admin_farm_menu")
async def admin_farm_menu(callback: CallbackQuery):
    """Farm jadvali bosh sahifasi."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q", show_alert=True)
        return

    async with async_session_maker() as session:
        text = await get_farm_list_text(session)
        markup = await build_farm_keyboard(session)

    await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "farm_add")
async def farm_add_start(callback: CallbackQuery, state: FSMContext):
    """Yangi farm qo'shish — vaqt va miqdor so'rash."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q", show_alert=True)
        return

    await callback.message.answer(
        "⏰ <b>Yangi farm qo'shish</b>\n\n"
        "Vaqt va miqdorni quyidagi formatda kiriting:\n"
        "<code>HH:MM MIQDOR</code>\n\n"
        "📌 Misollar:\n"
        "• <code>08:00 50</code>\n"
        "• <code>14:30 100</code>\n"
        "• <code>18:00 150</code>\n\n"
        "❌ Bekor qilish uchun /cancel yozing.",
        parse_mode="HTML",
    )
    await state.set_state(FarmScheduleState.waiting_input)
    await callback.answer()


@router.message(FarmScheduleState.waiting_input)
async def farm_add_process(message: Message, state: FSMContext):
    """Farm vaqt va miqdorini qabul qilib DB ga yozadi."""
    if not is_admin(message.from_user.id):
        return

    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ Bekor qilindi.")
        return

    parsed = parse_farm_input(message.text or "")
    if not parsed:
        await message.answer(
            "❌ <b>Noto'g'ri format!</b>\n\n"
            "To'g'ri format: <code>HH:MM MIQDOR</code>\n"
            "Masalan: <code>14:30 100</code>",
            parse_mode="HTML",
        )
        return

    hour, minute, amount = parsed

    async with async_session_maker() as session:
        repo = FarmScheduleRepo(session)

        # Bir xil vaqtda farm borligini tekshirish
        if await repo.exists(hour, minute):
            await message.answer(
                f"⚠️ <b>{hour:02d}:{minute:02d}</b> vaqtida farm allaqachon mavjud!\n"
                f"Avval uni o'chiring yoki tahrirlang.",
                parse_mode="HTML",
            )
            return

        new_schedule = await repo.add(hour=hour, minute=minute, amount=amount)

    # Schedulerni darhol yangilash
    from utils.scheduler import reload_farm_schedules
    # scheduler main.py dan import qilinadi — global object
    try:
        from main import scheduler as _scheduler
        await reload_farm_schedules(_scheduler)
        scheduler_msg = "✅ Scheduler yangilandi."
    except Exception as e:
        logger.warning(f"Scheduler yangilanmadi: {e}")
        scheduler_msg = "⚠️ Scheduler keyingi bot restart da yangilanadi."

    await state.clear()
    await message.answer(
        f"✅ <b>Farm qo'shildi!</b>\n\n"
        f"🕐 Vaqt: <b>{new_schedule.time_str()}</b>\n"
        f"💰 Miqdor: <b>{amount} 🪙</b> (har a'zo uchun)\n\n"
        f"{scheduler_msg}",
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("farm_info:"))
async def farm_info(callback: CallbackQuery):
    """Bitta farm haqida ma'lumot va amallar."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q", show_alert=True)
        return

    schedule_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        repo = FarmScheduleRepo(session)
        s = await repo.get_by_id(schedule_id)

    if not s:
        await callback.answer("Farm topilmadi!", show_alert=True)
        return

    status = "✅ Faol" if s.is_active else "❌ Nofaol"
    text = (
        f"🌾 <b>Farm ma'lumotlari</b>\n\n"
        f"🕐 Vaqt: <b>{s.time_str()}</b>\n"
        f"💰 Miqdor: <b>{s.amount} 🪙</b> (har a'zo uchun)\n"
        f"📌 Holat: {status}\n"
        f"🗓 Qo'shilgan: {s.created_at.strftime('%d.%m.%Y %H:%M')}"
    )
    markup = await build_farm_item_keyboard(schedule_id)
    await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("farm_toggle:"))
async def farm_toggle(callback: CallbackQuery):
    """Farm'ni faol/nofaol holatga o'tkazadi."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q", show_alert=True)
        return

    schedule_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        repo = FarmScheduleRepo(session)
        updated = await repo.toggle_active(schedule_id)

    if not updated:
        await callback.answer("Farm topilmadi!", show_alert=True)
        return

    # Schedulerni yangilash
    from utils.scheduler import reload_farm_schedules
    try:
        from main import scheduler as _scheduler
        await reload_farm_schedules(_scheduler)
    except Exception as e:
        logger.warning(f"Scheduler yangilanmadi: {e}")

    status_text = "✅ Faollashtirildi" if updated.is_active else "❌ O'chirildi"
    await callback.answer(f"{updated.time_str()} — {status_text}")

    # Sahifani yangilash
    markup = await build_farm_item_keyboard(schedule_id)
    status = "✅ Faol" if updated.is_active else "❌ Nofaol"
    text = (
        f"🌾 <b>Farm ma'lumotlari</b>\n\n"
        f"🕐 Vaqt: <b>{updated.time_str()}</b>\n"
        f"💰 Miqdor: <b>{updated.amount} 🪙</b> (har a'zo uchun)\n"
        f"📌 Holat: {status}"
    )
    await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")


@router.callback_query(F.data.startswith("farm_edit:"))
async def farm_edit_start(callback: CallbackQuery, state: FSMContext):
    """Farm miqdorini tahrirlash."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q", show_alert=True)
        return

    schedule_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        repo = FarmScheduleRepo(session)
        s = await repo.get_by_id(schedule_id)

    if not s:
        await callback.answer("Farm topilmadi!", show_alert=True)
        return

    await state.update_data(edit_schedule_id=schedule_id)
    await state.set_state(FarmScheduleState.waiting_edit)

    await callback.message.answer(
        f"✏️ <b>{s.time_str()}</b> farmi uchun yangi miqdorni kiriting:\n\n"
        f"Hozirgi miqdor: <b>{s.amount} 🪙</b>\n\n"
        f"❌ Bekor qilish uchun /cancel",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(FarmScheduleState.waiting_edit)
async def farm_edit_process(message: Message, state: FSMContext):
    """Tahrirlangan miqdorni saqlaydi."""
    if not is_admin(message.from_user.id):
        return

    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ Bekor qilindi.")
        return

    try:
        new_amount = int(message.text.strip())
        if new_amount <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("❌ Faqat musbat son kiriting!")
        return

    data = await state.get_data()
    schedule_id = data.get("edit_schedule_id")

    async with async_session_maker() as session:
        repo = FarmScheduleRepo(session)
        updated = await repo.update_amount(schedule_id, new_amount)

    if not updated:
        await state.clear()
        await message.answer("❌ Farm topilmadi.")
        return

    from utils.scheduler import reload_farm_schedules
    try:
        from main import scheduler as _scheduler
        await reload_farm_schedules(_scheduler)
        scheduler_msg = "✅ Scheduler yangilandi."
    except Exception as e:
        logger.warning(f"Scheduler yangilanmadi: {e}")
        scheduler_msg = "⚠️ Scheduler keyingi restart da yangilanadi."

    await state.clear()
    await message.answer(
        f"✅ Farm yangilandi!\n\n"
        f"🕐 Vaqt: <b>{updated.time_str()}</b>\n"
        f"💰 Yangi miqdor: <b>{new_amount} 🪙</b>\n\n"
        f"{scheduler_msg}",
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("farm_delete:"))
async def farm_delete(callback: CallbackQuery):
    """Farm jadvalini o'chiradi."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q", show_alert=True)
        return

    schedule_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        repo = FarmScheduleRepo(session)
        s = await repo.get_by_id(schedule_id)
        if not s:
            await callback.answer("Farm topilmadi!", show_alert=True)
            return
        time_str = s.time_str()
        success = await repo.delete(schedule_id)

    if not success:
        await callback.answer("O'chirishda xato!", show_alert=True)
        return

    from utils.scheduler import reload_farm_schedules
    try:
        from main import scheduler as _scheduler
        await reload_farm_schedules(_scheduler)
    except Exception as e:
        logger.warning(f"Scheduler yangilanmadi: {e}")

    await callback.answer(f"🗑 {time_str} farmi o'chirildi.")

    # Jadvalni ko'rsatish
    async with async_session_maker() as session:
        text = await get_farm_list_text(session)
        markup = await build_farm_keyboard(session)
    await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")


@router.callback_query(F.data == "farm_clear_confirm")
async def farm_clear_confirm(callback: CallbackQuery):
    """Barchasini o'chirishni tasdiqlash so'raydi."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Ha, barchasini o'chir", callback_data="farm_clear_yes")
    builder.button(text="❌ Yo'q, bekor qil",       callback_data="admin_farm_menu")
    builder.adjust(1)

    await callback.message.edit_text(
        "⚠️ <b>Haqiqatan ham barcha farm jadvallarini o'chirmoqchimisiz?</b>\n\n"
        "Bu amalni qaytarib bo'lmaydi!",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "farm_clear_yes")
async def farm_clear_all(callback: CallbackQuery):
    """Barcha farm jadvallarini o'chiradi."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q", show_alert=True)
        return

    async with async_session_maker() as session:
        repo = FarmScheduleRepo(session)
        count = await repo.clear_all()

    from utils.scheduler import reload_farm_schedules
    try:
        from main import scheduler as _scheduler
        await reload_farm_schedules(_scheduler)
    except Exception as e:
        logger.warning(f"Scheduler yangilanmadi: {e}")

    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Yangi farm qo'shish", callback_data="farm_add")
    builder.button(text="🔙 Admin menyu",          callback_data="admin_menu")
    builder.adjust(1)

    await callback.message.edit_text(
        f"🗑 <b>{count} ta farm jadvali o'chirildi.</b>\n\n"
        "Scheduler tozalandi. Yangi farmlar qo'shishingiz mumkin.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer(f"{count} ta farm o'chirildi.")


# ═══════════════════════════════════════════════════════════════════════════════
# OLTIN BERISH
# ═══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "admin_give_gold")
async def admin_give_gold_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q", show_alert=True)
        return

    async with async_session_maker() as session:
        house_repo = HouseRepo(session)
        houses = await house_repo.get_all_active()

    if not houses:
        await callback.answer("Xonadonlar topilmadi.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for h in houses:
        builder.button(text=f"🏰 {h.name}", callback_data=f"give_gold_house:{h.id}")
    builder.button(text="🔙 Orqaga", callback_data="admin_menu")
    builder.adjust(2)

    await callback.message.edit_text(
        "💰 <b>Oltin berish</b>\n\nXonadonni tanlang:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("give_gold_house:"))
async def admin_give_gold_house(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q", show_alert=True)
        return

    house_id = int(callback.data.split(":")[1])
    await state.update_data(target_house_id=house_id)
    await state.set_state(AdminState.waiting_gold_amount)

    await callback.message.answer(
        "💰 Qancha tanga berishni kiriting (musbat son):\n\n"
        "❌ Bekor qilish: /cancel",
    )
    await callback.answer()


@router.message(AdminState.waiting_gold_amount)
async def admin_give_gold_amount(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ Bekor qilindi.")
        return

    try:
        amount = int(message.text.strip())
        if amount <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("❌ Faqat musbat son kiriting!")
        return

    data = await state.get_data()
    house_id = data.get("target_house_id")

    async with async_session_maker() as session:
        house_repo = HouseRepo(session)
        house = await house_repo.get_by_id(house_id)
        if not house:
            await message.answer("❌ Xonadon topilmadi.")
            await state.clear()
            return
        await house_repo.update_treasury(house_id, amount)
        updated = await house_repo.get_by_id(house_id)

    await state.clear()
    await message.answer(
        f"✅ <b>{house.name}</b> xonadoniga <b>{amount} 🪙</b> berildi.\n"
        f"Yangi xazina: <b>{updated.treasury} 🪙</b>",
        parse_mode="HTML",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# BOZOR NARXLARI
# ═══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "admin_market")
async def admin_market_prices(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q", show_alert=True)
        return

    async with async_session_maker() as session:
        market_repo = MarketRepo(session)
        prices = await market_repo.get_all()

    if not prices:
        text = "🛒 <b>Bozor narxlari</b>\n\nHozircha narxlar belgilanmagan."
    else:
        lines = ["🛒 <b>Bozor narxlari:</b>\n"]
        for p in prices:
            lines.append(f"• {p.item_type}: <b>{p.price} 🪙</b>")
        text = "\n".join(lines)

    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Narx o'zgartirish", callback_data="admin_set_price")
    builder.button(text="🔙 Admin menyu",        callback_data="admin_menu")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_set_price")
async def admin_set_price_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q", show_alert=True)
        return

    await callback.message.answer(
        "🛒 Narx belgilash uchun quyidagi formatda kiriting:\n\n"
        "<code>MAHSULOT NARX</code>\n\n"
        "Mavjud mahsulotlar: <code>soldier</code>, <code>dragon</code>, <code>scorpion</code>\n"
        "Masalan: <code>soldier 500</code>\n\n"
        "❌ Bekor qilish: /cancel",
        parse_mode="HTML",
    )
    await state.set_state(AdminState.waiting_item_type)
    await callback.answer()


@router.message(AdminState.waiting_item_type)
async def admin_set_price_process(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ Bekor qilindi.")
        return

    parts = (message.text or "").strip().split()
    if len(parts) != 2:
        await message.answer("❌ Format: <code>MAHSULOT NARX</code>", parse_mode="HTML")
        return

    item_type, price_str = parts
    allowed = {"soldier", "dragon", "scorpion"}
    if item_type not in allowed:
        await message.answer(f"❌ Noto'g'ri mahsulot. Faqat: {', '.join(allowed)}")
        return

    try:
        price = int(price_str)
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Narx musbat son bo'lishi kerak!")
        return

    async with async_session_maker() as session:
        market_repo = MarketRepo(session)
        await market_repo.set_price(item_type, price)

    await state.clear()
    await message.answer(
        f"✅ <b>{item_type}</b> narxi <b>{price} 🪙</b> ga o'zgartirildi.",
        parse_mode="HTML",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# STATISTIKA
# ═══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q", show_alert=True)
        return

    async with async_session_maker() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)
        farm_repo = FarmScheduleRepo(session)

        users = await user_repo.get_all_active()
        houses = await house_repo.get_all_active()
        farm_schedules = await farm_repo.get_all_active()

    total_treasury = sum(h.treasury for h in houses)

    text = (
        f"📊 <b>Bot Statistikasi</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{len(users)}</b>\n"
        f"🏰 Xonadonlar: <b>{len(houses)}</b>\n"
        f"💰 Jami xazina: <b>{total_treasury:,} 🪙</b>\n"
        f"🌾 Faol farm jadvallar: <b>{len(farm_schedules)}</b>\n"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Admin menyu", callback_data="admin_menu")

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


# ═══════════════════════════════════════════════════════════════════════════════
# CANCEL HANDLER
# ═══════════════════════════════════════════════════════════════════════════════

@router.message(Command("cancel"))
async def cancel_handler(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Hozir hech qanday amal bajarilmayapti.")
        return
    await state.clear()
    await message.answer("❌ Amal bekor qilindi.")
