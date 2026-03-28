from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from database.models import RoleEnum


def main_menu_keyboard(role: RoleEnum) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="👤 Profil"), KeyboardButton(text="🏰 Xonadon"))
    builder.row(KeyboardButton(text="⚔️ Urush"), KeyboardButton(text="🛒 Bozor"))
    builder.row(KeyboardButton(text="🏦 Temir Bank"), KeyboardButton(text="📜 Xronika"))
    builder.row(KeyboardButton(text="💬 Ichki Chat"), KeyboardButton(text="🤝 Diplomatiya"))

    if role in [RoleEnum.ADMIN]:
        builder.row(KeyboardButton(text="🔧 Admin Panel"))

    return builder.as_markup(resize_keyboard=True)


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


def market_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🗡️ Askar Sotib Olish", callback_data="market:buy:soldier")
    builder.button(text="🐉 Ajdar Sotib Olish", callback_data="market:buy:dragon")
    builder.button(text="🏹 Skorpion Sotib Olish", callback_data="market:buy:scorpion")
    builder.button(text="📊 Narxlar", callback_data="market:prices")
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
    builder.adjust(2)
    return builder.as_markup()


def house_list_keyboard(houses: list, action_prefix: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for house in houses:
        builder.button(
            text=f"🏰 {house.name} ({house.region.value})",
            callback_data=f"{action_prefix}:{house.id}"
        )
    builder.adjust(1)
    return builder.as_markup()


def quantity_keyboard(item: str, max_qty: int = 100) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for qty in [1, 5, 10, 50, 100]:
        if qty <= max_qty:
            builder.button(text=str(qty), callback_data=f"qty:{item}:{qty}")
    builder.button(text="✏️ Boshqa", callback_data=f"qty:{item}:custom")
    builder.adjust(5)
    return builder.as_markup()
