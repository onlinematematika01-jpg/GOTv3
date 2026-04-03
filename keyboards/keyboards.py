from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from database.models import RoleEnum


def back_button(callback_data: str = "back:main") -> list:
    """Orqaga tugma — inline keyboard uchun"""
    return [InlineKeyboardButton(text="🔙 Orqaga", callback_data=callback_data)]


def main_menu_keyboard(role: RoleEnum) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="👤 Profil"), KeyboardButton(text="🏰 Xonadon"))
    builder.row(KeyboardButton(text="⚔️ Urush"), KeyboardButton(text="🛒 Bozor"))
    builder.row(KeyboardButton(text="🏦 Temir Bank"), KeyboardButton(text="📜 Xronika"))
    builder.row(KeyboardButton(text="💬 Ichki Chat"), KeyboardButton(text="🤝 Diplomatiya"))
    builder.row(KeyboardButton(text="🏆 Reyting"))
    if role in [RoleEnum.LORD, RoleEnum.HIGH_LORD]:
        builder.row(KeyboardButton(text="👑 Hukmdorlik Da'vosi"))
    if role in [RoleEnum.ADMIN]:
        builder.row(KeyboardButton(text="🔧 Admin Panel"))
    return builder.as_markup(resize_keyboard=True)


def rating_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⚡ Umumiy Kuch", callback_data="rating:power")
    builder.button(text="🗡️ Askarlar", callback_data="rating:soldiers")
    builder.button(text="💰 Oltin", callback_data="rating:gold")
    builder.button(text="🐉 Jangchilar", callback_data="rating:dragons")
    builder.button(text="🏆 Jangda Yutgani", callback_data="rating:wins")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def war_menu_keyboard(is_lord: bool, has_active_war: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if is_lord and not has_active_war:
        builder.button(text="⚔️ Urush E'lon Qilish", callback_data="war:declare")
    if has_active_war:
        builder.button(text="🏳️ Taslim Bo'lish", callback_data="war:surrender")
        builder.button(text="🗡️ Jangga Kirish", callback_data="war:fight")
    builder.button(text="📊 Urush Holati", callback_data="war:status")
    builder.adjust(1)
    return builder.as_markup()


def market_keyboard(custom_items=None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🗡️ Askar Sotib Olish", callback_data="market:buy:soldier")
    builder.button(text="🐉 Ajdar Sotib Olish", callback_data="market:buy:dragon")
    builder.button(text="🏹 Skorpion Sotib Olish", callback_data="market:buy:scorpion")
    if custom_items:
        for item in custom_items:
            builder.button(
                text=f"{item.emoji} {item.name} Sotib Olish",
                callback_data=f"market:custom:{item.id}"
            )
    builder.button(text="📊 Narxlar", callback_data="market:prices")
    builder.adjust(1)
    return builder.as_markup()


def custom_item_market_keyboard(items) -> InlineKeyboardMarkup:
    """Faqat maxsus itemlar uchun keyboard"""
    builder = InlineKeyboardBuilder()
    for item in items:
        builder.button(
            text=f"{item.emoji} {item.name} — {item.price:,} tanga",
            callback_data=f"market:custom:{item.id}"
        )
    builder.button(text="🔙 Orqaga", callback_data="market:back")
    builder.adjust(1)
    return builder.as_markup()


def iron_bank_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💰 Qarz Olish", callback_data="bank:loan")
    builder.button(text="💸 Qarz To'lash", callback_data="bank:repay")
    builder.button(text="📋 Qarz Holati", callback_data="bank:status")
    builder.adjust(2)
    return builder.as_markup()


def diplomacy_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🤝 Ittifoq Tuzish", callback_data="diplo:alliance")
    builder.button(text="❌ Ittifoqni Buzish", callback_data="diplo:break")
    builder.button(text="📋 Ittifoqlarim", callback_data="diplo:list")
    builder.adjust(1)
    return builder.as_markup()


def surrender_or_fight_keyboard(war_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🏳️ Taslim Bo'lish (50% resurs berish)", callback_data=f"war:do_surrender:{war_id}")
    builder.button(text="⚔️ Jangga Kirish!", callback_data=f"war:do_fight:{war_id}")
    builder.adjust(1)
    return builder.as_markup()


def confirm_keyboard(action: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Tasdiqlash", callback_data=f"confirm:{action}")
    builder.button(text="❌ Bekor Qilish", callback_data="cancel")
    builder.adjust(2)
    return builder.as_markup()


def admin_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💰 Narx O'zgartirish", callback_data="admin:prices")
    builder.button(text="🏦 Bank Foiz O'zgartirish", callback_data="admin:interest")
    builder.button(text="👥 Foydalanuvchilar", callback_data="admin:users")
    builder.button(text="🏰 Xonadonlar", callback_data="admin:houses")
    builder.button(text="📢 Xabar Yuborish", callback_data="admin:broadcast")
    builder.button(text="🏰 Xonadon Qo'shish", callback_data="admin:add_house")
    builder.button(text="👑 Hukmdor Tayinlash", callback_data="admin:set_high_lord")
    builder.button(text="🏦 Bank Limiti", callback_data="admin:bank_limits")
    builder.button(text="🌾 Farm Jadvali", callback_data="admin:farm_schedule")
    builder.button(text="💸 Qarzdorlar", callback_data="admin:debtors")
    builder.button(text="⚔️ Urush Seanslar", callback_data="admin:war_sessions")
    builder.button(text="🔀 A'zo Ko'chirish", callback_data="admin:transfer_member")
    builder.button(text="🗑 Bazani Tozalash", callback_data="admin:reset_db")
    builder.button(text="🧪 Maxsus Itemlar", callback_data="admin:custom_items")
    builder.adjust(2)
    return builder.as_markup()


def admin_keyboard_with_back() -> InlineKeyboardMarkup:
    """Admin panel uchun orqaga tugmasiz (asosiy menyu Reply tugma)"""
    return admin_keyboard()


def house_list_keyboard(houses: list, action_prefix: str, back_to: str = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for house in houses:
        builder.button(
            text=f"🏰 {house.name} ({house.region.value})",
            callback_data=f"{action_prefix}:{house.id}"
        )
    if back_to:
        builder.button(text="🔙 Orqaga", callback_data=back_to)
    builder.adjust(1)
    return builder.as_markup()


def quantity_keyboard(item: str, max_qty: int = 100) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for qty in [1, 5, 10, 50, 100]:
        if qty <= max_qty:
            builder.button(text=str(qty), callback_data=f"qty:{item}:{qty}")
    builder.button(text="✏️ Boshqa", callback_data=f"qty:{item}:custom")
    builder.button(text="🔙 Orqaga", callback_data="market:back")
    builder.adjust(5)
    return builder.as_markup()


# ── Orqaga tugmali keyboard yordamchi funksiyalar ──────────────────────────

def with_back(markup: InlineKeyboardMarkup, back_to: str) -> InlineKeyboardMarkup:
    """Mavjud inline keyboard ga orqaga tugma qo'shadi"""
    buttons = markup.inline_keyboard
    buttons.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data=back_to)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_only_keyboard(back_to: str) -> InlineKeyboardMarkup:
    """Faqat orqaga tugma"""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 Orqaga", callback_data=back_to)
    ]])


def alliance_request_keyboard(from_house_id: int, to_house_id: int) -> InlineKeyboardMarkup:
    """Ittifoq taklifini qabul qilish yoki rad etish tugmalari"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Qabul qilish",
                callback_data=f"diplo:accept:{from_house_id}:{to_house_id}"
            ),
            InlineKeyboardButton(
                text="❌ Rad etish",
                callback_data=f"diplo:reject:{from_house_id}:{to_house_id}"
            ),
        ]
    ])


def subscription_keyboard(channel_link: str) -> InlineKeyboardMarkup:
    """Majburiy obuna uchun kanal havolasi va tekshirish tugmasi"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="📢 Kanalga o'tish",
                url=channel_link,
            )
        ],
        [
            InlineKeyboardButton(
                text="✅ A'zo bo'ldim, tekshirish",
                callback_data="check_subscription",
            )
        ],
    ])


def custom_items_menu_keyboard() -> InlineKeyboardMarkup:
    """Maxsus itemlar boshqaruv menyusi"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Yangi Item Qo'shish", callback_data="admin:item:add")],
        [InlineKeyboardButton(text="📋 Barcha Itemlar", callback_data="admin:item:list")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin:back")],
    ])


def item_type_keyboard() -> InlineKeyboardMarkup:
    """Item turi tanlash"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🐉 Hujum (ajdar kabi)", callback_data="itype:attack")],
        [InlineKeyboardButton(text="🏹 Mudofaa (chayon kabi)", callback_data="itype:defense")],
        [InlineKeyboardButton(text="🗡️ Askar (qo'shma)", callback_data="itype:soldier")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin:custom_items")],
    ])


def item_manage_keyboard(item_id: int, is_active: bool) -> InlineKeyboardMarkup:
    """Item boshqarish tugmalari"""
    toggle_text = "🔴 O'chirish" if is_active else "🟢 Yoqish"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle_text, callback_data=f"admin:item:toggle:{item_id}")],
        [InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"admin:item:delete:{item_id}")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin:item:list")],
    ])
