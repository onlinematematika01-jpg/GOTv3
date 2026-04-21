from aiogram import Bot
from config.settings import settings
import logging

logger = logging.getLogger(__name__)


async def post_to_chronicle(bot: Bot, text: str, channel: str = "chronicle") -> int | None:
    """Telegram kanalga voqea post qilish.

    channel parametri:
      "chronicle"    — asosiy voqealar kanali (CHRONICLE_CHANNEL_ID)
      "bank_market"  — temir bank va bozor kanali (BANK_MARKET_CHANNEL_ID)
                       agar BANK_MARKET_CHANNEL_ID yo'q bo'lsa, CHRONICLE_CHANNEL_ID ishlatiladi
    """
    if channel == "bank_market":
        channel_id = settings.BANK_MARKET_CHANNEL_ID or settings.CHRONICLE_CHANNEL_ID
    else:
        channel_id = settings.CHRONICLE_CHANNEL_ID

    logger.info(f"post_to_chronicle: channel={channel!r}, channel_id={channel_id!r}")

    if not channel_id:
        logger.warning(f"post_to_chronicle: channel_id topilmadi, yuborilmadi (channel={channel!r})")
        return None

    try:
        msg = await bot.send_message(
            chat_id=int(channel_id),
            text=text,
            parse_mode="HTML",
        )
        logger.info(f"post_to_chronicle: xabar yuborildi chat_id={channel_id}, msg_id={msg.message_id}")
        return msg.message_id
    except Exception as e:
        logger.error(f"post_to_chronicle xato (channel={channel!r}, chat_id={channel_id}): {e}")
        return None


EMOJIS = {
    "war_declared":    "⚔️",
    "war_ended":       "🏆",
    "surrender":       "🏳️",
    "new_lord":        "👑",
    "exile":           "🚪",
    "loan":            "🏦",
    "repay":           "💸",
    "alliance":        "🤝",
    "betrayal":        "🗡️",
    "tribute":         "💰",
    "war_ally_joined": "🤝",
    "war_power_update":"📊",
    "lord_captured":   "🔗",
    "lord_freed":      "🕊️",
    "lord_executed":   "💀",
    "lord_ransomed":   "💰",
}


async def post_war_power_update(bot: Bot, war_id: int):
    """Urush kuchlar nisbatini kanalga yuboradi"""
    from database.engine import AsyncSessionFactory
    from database.models import War, WarAllySupport, ItemTypeEnum
    from database.repositories import HouseRepo, CustomItemRepo
    from sqlalchemy import select

    async with AsyncSessionFactory() as session:
        war_result = await session.execute(
            select(War).where(War.id == war_id)
        )
        war = war_result.scalar_one_or_none()
        if not war:
            return

        house_repo = HouseRepo(session)
        custom_repo = CustomItemRepo(session)
        attacker = await house_repo.get_by_id(war.attacker_house_id)
        defender = await house_repo.get_by_id(war.defender_house_id)
        if not attacker or not defender:
            return

        def calc_item_power(items_with_info):
            atk = def_ = sol = 0
            lines = []
            for row in items_with_info:
                item = row.item
                qty = row.quantity
                if item.item_type == ItemTypeEnum.ATTACK:
                    atk += item.attack_power * qty
                    lines.append(f"  └ {item.emoji}{item.name}×{qty} (+{item.attack_power * qty} hujum)")
                elif item.item_type == ItemTypeEnum.DEFENSE:
                    def_ += item.defense_power * qty
                    lines.append(f"  └ {item.emoji}{item.name}×{qty} (+{item.defense_power * qty} himoya)")
                elif item.item_type == ItemTypeEnum.SOLDIER:
                    sol += item.attack_power * qty
                    lines.append(f"  └ {item.emoji}{item.name}×{qty} (+{item.attack_power * qty} askar kuchi)")
            return atk, def_, sol, lines

        att_items = await custom_repo.get_house_items_with_info(attacker.id)
        def_items = await custom_repo.get_house_items_with_info(defender.id)
        att_item_atk, att_item_def, att_item_sol, att_item_lines = calc_item_power(att_items)
        def_item_atk, def_item_def, def_item_sol, def_item_lines = calc_item_power(def_items)

        sup_result = await session.execute(
            select(WarAllySupport).where(WarAllySupport.war_id == war_id)
        )
        supports = sup_result.scalars().all()

        att_ally_s = att_ally_sc = 0
        def_ally_s = def_ally_sc = 0
        att_allies = []
        def_allies = []

        for sup in supports:
            ally = await house_repo.get_by_id(sup.ally_house_id)
            ally_name = ally.name if ally else f"#{sup.ally_house_id}"

            ally_item_atk = ally_item_def = ally_item_sol = 0
            if ally and sup.join_type == "full":
                ally_items = await custom_repo.get_house_items_with_info(ally.id)
                ally_item_atk, ally_item_def, ally_item_sol, _ = calc_item_power(ally_items)

            if sup.side == "attacker":
                att_ally_s += sup.soldiers + ally_item_sol
                att_ally_sc += sup.scorpions
                att_item_atk += ally_item_atk
                att_item_def += ally_item_def
                if sup.join_type == "gold":
                    att_allies.append(f"  └ {ally_name}: 💰{sup.gold} oltin")
                else:
                    att_allies.append(f"  └ {ally_name}: 🗡️{sup.soldiers} 🏹{sup.scorpions}")
            else:
                def_ally_s += sup.soldiers + ally_item_sol
                def_ally_sc += sup.scorpions
                def_item_atk += ally_item_atk
                def_item_def += ally_item_def
                if sup.join_type == "gold":
                    def_allies.append(f"  └ {ally_name}: 💰{sup.gold} oltin")
                else:
                    def_allies.append(f"  └ {ally_name}: 🗡️{sup.soldiers} 🏹{sup.scorpions}")

        from config.settings import settings as _s
        att_total_s = attacker.total_soldiers + att_ally_s
        att_total_sc = attacker.total_scorpions + att_ally_sc
        att_power = (
            att_total_s
            + att_total_sc * 2
            + attacker.total_dragons * _s.DRAGON_KILLS_SOLDIERS
            + att_item_atk + att_item_def + att_item_sol
        )

        def_total_s = defender.total_soldiers + def_ally_s
        def_total_sc = defender.total_scorpions + def_ally_sc
        def_power = (
            def_total_s
            + def_total_sc * 2
            + defender.total_dragons * _s.DRAGON_KILLS_SOLDIERS
            + def_item_atk + def_item_def + def_item_sol
        )

        total = att_power + def_power
        att_pct = att_power * 100 // total if total > 0 else 50
        def_pct = 100 - att_pct

        bar_len = 10
        att_bar = "🟥" * (att_pct * bar_len // 100) + "⬜" * (bar_len - att_pct * bar_len // 100)
        def_bar = "🟦" * (def_pct * bar_len // 100) + "⬜" * (bar_len - def_pct * bar_len // 100)

        text = (
            f"📊 <b>KUCHLAR NISBATI</b>\n\n"
            f"⚔️ <b>{attacker.name}</b> (Hujumchi)\n"
            f"🗡️ {attacker.total_soldiers} askar | 🐉 {attacker.total_dragons} ajdar | 🏹 {attacker.total_scorpions} skorpion\n"
        )
        if att_item_lines:
            text += "🔱 Maxsus qurollar:\n" + "\n".join(att_item_lines) + "\n"
        if att_allies:
            text += "🤝 Ittifoqchilar:\n" + "\n".join(att_allies) + "\n"
        text += f"💪 Jami kuch: {att_power} | {att_bar} {att_pct}%\n\n"

        text += (
            f"🛡️ <b>{defender.name}</b> (Mudofaachi)\n"
            f"🗡️ {defender.total_soldiers} askar | 🐉 {defender.total_dragons} ajdar | 🏹 {defender.total_scorpions} skorpion\n"
        )
        if def_item_lines:
            text += "🔱 Maxsus qurollar:\n" + "\n".join(def_item_lines) + "\n"
        if def_allies:
            text += "🤝 Ittifoqchilar:\n" + "\n".join(def_allies) + "\n"
        text += f"💪 Jami kuch: {def_power} | {def_bar} {def_pct}%"

    await post_to_chronicle(bot, text)


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
        "loan": (
            "🏦 <b>TEMIR BANK: QARZ OLINDI!</b>\n\n"
            "🏰 <b>{house}</b> xonadoni Temir Bankdan qarz oldi.\n"
            "💰 Qarz miqdori: {amount:,} tanga\n"
            "📈 Foiz bilan qaytarish: {total_due:,} tanga"
        ),
        "repay": (
            "💸 <b>TEMIR BANK: QARZ TO'LANDI!</b>\n\n"
            "🏰 <b>{house}</b> xonadoni Temir Bankka qarz to'ladi.\n"
            "💸 To'langan miqdor: {paid:,} tanga\n"
            "📋 Qolgan qarz: {remaining:,} tanga"
        ),
        "lord_captured": (
            "🔗 <b>LORD ASIRGA OLINDI!</b>\n\n"
            "🏰 <b>{captor}</b> xonadoni <b>{prisoner_house}</b> xonadoni lordi "
            "<b>{prisoner}</b>ni asirga oldi!\n"
            "📦 Resurslar g'olibga o'tkazildi."
        ),
        "lord_freed": (
            "🕊️ <b>LORD OZOD BO'LDI!</b>\n\n"
            "🏰 <b>{prisoner}</b> lord asirlikdan ozod bo'ldi!"
        ),
        "lord_executed": (
            "💀 <b>LORD O'LDIRILDI!</b>\n\n"
            "🏰 <b>{captor}</b> xonadoni <b>{prisoner}</b> lordini o'ldirdi!\n\n"
            "⚠️ OGOHLANTIRISH: Bu lordga qarshi endi barcha xonadon urush e'lon qilishi mumkin!"
        ),
        "lord_ransomed": (
            "💰 <b>TOVON TO'LANDI!</b>\n\n"
            "🏰 <b>{payer}</b> xonadoni <b>{prisoner}</b> lordini tovon to'lab ozod qildi.\n"
            "💸 Tovon: {amount:,} tanga"
        ),
    }
    template = templates.get(event_type, "📜 {description}")
    try:
        return template.format(**kwargs)
    except KeyError:
        return str(kwargs)
