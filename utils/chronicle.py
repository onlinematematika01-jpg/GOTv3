from aiogram import Bot
from config.settings import settings
import logging

logger = logging.getLogger(__name__)

async def post_to_chronicle(bot: Bot, text: str) -> int | None:
    """Telegram kanalga voqea post qilish"""
    if not settings.CHRONICLE_CHANNEL_ID:
        return None
    try:
        msg = await bot.send_message(
            chat_id=settings.CHRONICLE_CHANNEL_ID,
            text=text,
            parse_mode="HTML",
        )
        return msg.message_id
    except Exception as e:
        logger.error(f"Xronika post qilishda xato: {e}")
        return None

EMOJIS = {
    "war_declared": "⚔️",
    "war_ended": "🏆",
    "surrender": "🏳️",
    "new_lord": "👑",
    "exile": "🚪",
    "loan": "🏦",
    "repay": "💸",
    "alliance": "🤝",
    "betrayal": "🗡️",
    "tribute": "💰",
}

def format_chronicle(event_type: str, **kwargs) -> str:
    templates = {
        "war_declared": (
            "⚔️ <b>URUSH E'LONI!</b>\n\n"
            "🏰 <b>{attacker}</b> → <b>{defender}</b> ga urush ochdi!\n"
            "⏰ Grace Period: 1 soat\n"
            "🗺️ Hudud: {region}"
        ),
        "war_ended": (
            "🏆 <b>JANG TUGADI!</b>\n\n"
            "👑 G'olib: <b>{winner}</b>\n"
            "😔 Mag'lub: <b>{loser}</b>\n"
            "💰 O'lja: {loot} oltin | 🗡️ {loot_s} askar | 🐉 {loot_d} ajdar\n"
            "⚔️ Hujumchi yo'qotdi: {att_lost_s} askar, {att_lost_d} ajdar\n"
            "🛡️ Mudofaa yo'qotdi: {def_lost_s} askar, {def_lost_d} ajdar"
        ),
        "surrender": (
            "🏳️ <b>TASLIM BO'LDI!</b>\n\n"
            "🏰 <b>{loser}</b> kuchli bosim ostida taslim bo'ldi.\n"
            "🏰 <b>{winner}</b> g'alaba qozondi va doimiy soliq o'rnatdi.\n"
            "💰 O'lja: {loot} oltin"
        ),
        "new_lord": (
            "👑 <b>YANGI LORD!</b>\n\n"
            "🏰 <b>{house}</b> xonadonida yangi lord:\n"
            "🗡️ <b>{lord_name}</b>\n"
            "Sobiq lord: {old_lord}"
        ),
        "exile": (
            "🚪 <b>SURGUN!</b>\n\n"
            "🏰 <b>{user}</b> mag'lubiyatdan so'ng surgun qilindi.\n"
            "Yangi xonadon: <b>{new_house}</b>"
        ),
        "betrayal": (
            "🗡️ <b>XIYONAT!</b>\n\n"
            "🏰 <b>{user}</b> jang paytida o'z lordini tark etdi!\n"
            "Panoh so'ragan xonadon: <b>{refuge_house}</b>"
        ),
        "alliance": (
            "🤝 <b>ITTIFOQ TUZILDI!</b>\n\n"
            "🏰 <b>{house1}</b> va <b>{house2}</b> ittifoq tuzdi."
        ),
        # Yangi: qarz olish
        "loan": (
            "🏦 <b>TEMIR BANK: QARZ OLINDI!</b>\n\n"
            "🏰 <b>{house}</b> xonadoni Temir Bankdan qarz oldi.\n"
            "💰 Qarz miqdori: {amount:,} tanga\n"
            "📈 Foiz bilan qaytarish: {total_due:,} tanga"
        ),
        # Yangi: qarz to'lash
        "repay": (
            "💸 <b>TEMIR BANK: QARZ TO'LANDI!</b>\n\n"
            "🏰 <b>{house}</b> xonadoni Temir Bankka qarz to'ladi.\n"
            "💸 To'langan miqdor: {paid:,} tanga\n"
            "📋 Qolgan qarz: {remaining:,} tanga"
        ),
    }
    template = templates.get(event_type, "📜 {description}")
    try:
        return template.format(**kwargs)
    except KeyError:
        return str(kwargs)
