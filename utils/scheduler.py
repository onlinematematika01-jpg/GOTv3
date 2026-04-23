from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot
from database.engine import AsyncSessionFactory
from database.repositories import UserRepo, HouseRepo, WarRepo, IronBankRepo, ChronicleRepo
from database.models import RoleEnum, WarStatusEnum
from sqlalchemy import select, update
from database.models import User, House
from config.settings import settings
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Global scheduler referensini saqlash uchun — circular import muammosini hal qiladi
_global_scheduler: AsyncIOScheduler | None = None
_global_bot = None


def set_global_scheduler(scheduler: AsyncIOScheduler):
    """main.py dan scheduler o'rnatilganda chaqiriladi"""
    global _global_scheduler
    _global_scheduler = scheduler


def set_global_bot(bot):
    global _global_bot
    _global_bot = bot


def get_global_scheduler() -> AsyncIOScheduler:
    if _global_scheduler is None:
        raise RuntimeError("Scheduler hali o'rnatilmagan. set_global_scheduler() chaqiring.")
    return _global_scheduler


async def reload_deposit_job(hour: int, minute: int):
    """Admin foiz vaqtini o'zgartirganida deposit_check jobini qayta yuklaydi"""
    scheduler = get_global_scheduler()
    bot = _global_bot
    scheduler.add_job(
        process_deposits_job,
        CronTrigger(hour=hour, minute=minute, timezone="Asia/Tashkent"),
        args=[bot],
        id="deposit_check",
        replace_existing=True,
    )
    logger.info(f"Deposit job qayta yuklandi: {hour:02d}:{minute:02d} Tashkent")

async def daily_farm_job(bot: Bot, scheduled_amount: int = 0):
    """Kunlik farm: jadval bo'yicha belgilangan miqdorni xonadon xazinasiga qo'shadi.

    scheduled_amount — admin tomonidan lord uchun belgilangan miqdor.
    A'zolar har doim settings.MEMBER_DAILY_INCOME (20) tanga tushiradi.
    """
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)

        result = await session.execute(select(User).where(User.is_active == True))
        all_users = result.scalars().all()

        # Har xonadon bo'yicha farm summani hisoblash
        # house_farm_detail: {house_id: {"lord": int, "members": int, "member_count": int, "lord_count": int}}
        house_farm_detail: dict[int, dict] = {}
        for user in all_users:
            if user.role == RoleEnum.ADMIN or not user.house_id:
                continue
            hid = user.house_id
            if hid not in house_farm_detail:
                house_farm_detail[hid] = {"lord": 0, "members": 0, "member_count": 0, "lord_count": 0}

            if user.role in [RoleEnum.HIGH_LORD, RoleEnum.LORD]:
                # Lord uchun: admin belgilagan miqdor yoki default
                lord_amount = scheduled_amount if scheduled_amount > 0 else settings.LORD_DAILY_INCOME
                house_farm_detail[hid]["lord"] += lord_amount
                house_farm_detail[hid]["lord_count"] += 1
            else:
                # A'zo uchun: har doim MEMBER_DAILY_INCOME (20 tanga)
                house_farm_detail[hid]["members"] += settings.MEMBER_DAILY_INCOME
                house_farm_detail[hid]["member_count"] += 1

        # Xazinalarga qo'shish
        for house_id, detail in house_farm_detail.items():
            total = detail["lord"] + detail["members"]
            if total > 0:
                await house_repo.update_treasury(house_id, total)

        # O'lpon: vassal (bosib olingan) xonadon Hukmdor xonadoniga xazinasining 10% ini to'laydi
        all_houses = await house_repo.get_all()
        for house in all_houses:
            if not house.is_under_occupation or not house.occupier_house_id:
                continue
            result = await session.execute(
                select(House).where(House.id == house.id)
            )
            h = result.scalar_one_or_none()
            if not h or h.treasury <= 0:
                continue
            tribute = int(h.treasury * 0.10)  # Xazinaning 10%
            actual_tribute = min(tribute, h.treasury)
            if actual_tribute > 0:
                await house_repo.update_treasury(house.id, -actual_tribute)
                await house_repo.update_treasury(house.occupier_house_id, actual_tribute)

                # Hukmdor xonadonini topish
                occupier_result = await session.execute(
                    select(House).where(House.id == house.occupier_house_id)
                )
                occupier = occupier_result.scalar_one_or_none()

                # Vassalning lordiga xabar — kimga to'layotganini bilsin
                if h.lord_id:
                    try:
                        await bot.send_message(
                            h.lord_id,
                            f"💸 <b>O'lpon to'landi!</b>\n\n"
                            f"Xazinangizning 10% i ({actual_tribute:,} tanga)\n"
                            f"👑 <b>{occupier.name if occupier else 'Hukmdor'}</b> xonadoniga o'tkazildi.",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass

                # Hukmdorning lordiga xabar — kimdan olayotganini bilsin
                if occupier and occupier.lord_id:
                    try:
                        await bot.send_message(
                            occupier.lord_id,
                            f"💰 <b>O'lpon olindi!</b>\n\n"
                            f"🏰 <b>{h.name}</b> xonadonidan\n"
                            f"{actual_tribute:,} tanga xazinangizga o'tkazildi.",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass

        # Referal hisoblagichni nollash
        await session.execute(update(User).values(referral_count_today=0))
        await session.commit()

        logger.info("✅ Kunlik farm bajarildi")

        # Xabarnoma — barcha faol a'zolarga (to'g'ri miqdorlar bilan)
        for user in all_users:
            if user.role == RoleEnum.ADMIN or not user.house_id:
                continue
            hid = user.house_id
            detail = house_farm_detail.get(hid, {})
            try:
                if user.role in [RoleEnum.HIGH_LORD, RoleEnum.LORD]:
                    lord_amount = scheduled_amount if scheduled_amount > 0 else settings.LORD_DAILY_INCOME
                    member_count = detail.get("member_count", 0)
                    member_total = detail.get("members", 0)
                    total_added = detail.get("lord", 0) + member_total
                    msg = (
                        f"🌾 <b>Kunlik farm!</b>\n\n"
                        f"👑 Lord hissasi: +{lord_amount} tanga\n"
                    )
                    if member_count > 0:
                        msg += f"⚔️ A'zolar hissasi ({member_count} kishi): +{member_total} tanga\n"
                    msg += f"\n💰 Jami xazinaga: +{total_added} tanga"
                    await bot.send_message(user.id, msg, parse_mode="HTML")
                else:
                    await bot.send_message(
                        user.id,
                        f"🌾 <b>Kunlik farm!</b>\n"
                        f"+{settings.MEMBER_DAILY_INCOME} tanga xonadon xazinasiga qo'shildi.",
                        parse_mode="HTML"
                    )
            except Exception:
                pass



async def _transfer_custom_item_loot(session, loser_id: int, winner_id: int):
    """
    Yutqazgan xonadon custom itemlarining WAR_LOOT_PERCENT (51%) ini
    g'olib xonadonga o'tkazadi. commit() CHAQIRILMAYDI — caller qiladi.
    """
    import math
    from database.models import HouseCustomItem
    from sqlalchemy import select as _sa_select
    from config.settings import settings

    loser_items_res = await session.execute(
        _sa_select(HouseCustomItem).where(
            HouseCustomItem.house_id == loser_id,
            HouseCustomItem.quantity > 0,
        )
    )
    loser_rows = loser_items_res.scalars().all()

    for row in loser_rows:
        loot_qty = math.ceil(row.quantity * settings.WAR_LOOT_PERCENT)
        if loot_qty <= 0:
            continue
        # Yutqazgandan ayirish
        row.quantity = max(0, row.quantity - loot_qty)
        # G'olibga qo'shish
        winner_res = await session.execute(
            _sa_select(HouseCustomItem).where(
                HouseCustomItem.house_id == winner_id,
                HouseCustomItem.item_id == row.item_id,
            )
        )
        winner_row = winner_res.scalar_one_or_none()
        if winner_row:
            winner_row.quantity += loot_qty
        else:
            session.add(HouseCustomItem(house_id=winner_id, item_id=row.item_id, quantity=loot_qty))


async def _run_war(war, bot, session):
    """
    Urushni hisoblash va natijalarni yuborish.
    Grace tugaganda darhol va 23:00 da ham chaqiriladi.
    """
    from utils.battle import calculate_battle, AllyContribution
    from utils.chronicle import post_to_chronicle, format_chronicle
    from database.models import WarAllySupport
    from sqlalchemy import select as sa_select
    from sqlalchemy.orm import selectinload as sa_selectinload

    war_repo = WarRepo(session)
    house_repo = HouseRepo(session)
    chronicle_repo = ChronicleRepo(session)

    attacker = war.attacker
    defender = war.defender

    # ── Omonatdagi resurslarni jangdan chiqarib qo'yish ──────────────
    from database.repositories import IronBankDepositRepo
    dep_repo = IronBankDepositRepo(session)
    att_deposit = await dep_repo.get_active(attacker.id)
    def_deposit = await dep_repo.get_active(defender.id)

    if att_deposit:
        attacker.total_soldiers  = max(0, attacker.total_soldiers  - att_deposit.soldiers)
        attacker.total_dragons   = max(0, attacker.total_dragons   - att_deposit.dragons)
        attacker.total_scorpions = max(0, attacker.total_scorpions - att_deposit.scorpions)

    if def_deposit:
        defender.total_soldiers  = max(0, defender.total_soldiers  - def_deposit.soldiers)
        defender.total_dragons   = max(0, defender.total_dragons   - def_deposit.dragons)
        defender.total_scorpions = max(0, defender.total_scorpions - def_deposit.scorpions)

    # Ittifoqchi yordamlarini yuklash
    ally_result = await session.execute(
        sa_select(WarAllySupport)
        .where(WarAllySupport.war_id == war.id)
        .options(sa_selectinload(WarAllySupport.ally_house))
    )
    ally_supports = ally_result.scalars().all()

    attacker_allies = [
        AllyContribution(
            house_id=s.ally_house_id,
            house_name=s.ally_house.name if s.ally_house else str(s.ally_house_id),
            join_type=s.join_type,
            soldiers=s.soldiers,
            dragons=s.dragons,
            scorpions=s.scorpions,
        )
        for s in ally_supports if s.side == "attacker"
    ]
    defender_allies = [
        AllyContribution(
            house_id=s.ally_house_id,
            house_name=s.ally_house.name if s.ally_house else str(s.ally_house_id),
            join_type=s.join_type,
            soldiers=s.soldiers,
            dragons=s.dragons,
            scorpions=s.scorpions,
        )
        for s in ally_supports if s.side == "defender"
    ]

    # ── Custom itemlarni xonadonlarga bog'lash (battle uchun) ──────────
    from database.repositories import CustomItemRepo
    custom_repo = CustomItemRepo(session)

    att_ci_rows = await custom_repo.get_house_items_with_info(attacker.id)
    def_ci_rows = await custom_repo.get_house_items_with_info(defender.id)

    # Jangdan OLDIN snapshot: {item_id: qty}
    att_items_before = {row.item_id: row.quantity for row in att_ci_rows}
    def_items_before = {row.item_id: row.quantity for row in def_ci_rows}

    attacker._custom_items = [{"item": row.item, "qty": row.quantity} for row in att_ci_rows]
    defender._custom_items = [{"item": row.item, "qty": row.quantity} for row in def_ci_rows]

    # Hisob-kitob
    result = calculate_battle(
        attacker, defender,
        defender_gold=defender.treasury,
        attacker_allies=attacker_allies,
        defender_allies=defender_allies,
    )

    # ── Jangda halok bo'lgan itemlarni DB ga yozish (commit() siz) ─────
    # calculate_battle ichida _custom_items[i]["qty"] yangilangan (kamaytirgan)
    # Shu farqni DB ga ayiramiz — barcha item turlari (yangi va eskilar) uchun
    from database.models import HouseCustomItem
    from sqlalchemy import select as _sa_select

    async def _apply_battle_item_losses(house, items_before: dict):
        """Jangdan keyin _custom_items dagi qty ni DB dagi qty bilan solishtiradi
        va farqni (yo'qotishni) DB ga yozadi. commit() CHAQIRILMAYDI."""
        items_after = {entry["item"].id: entry["qty"] for entry in (house._custom_items or [])}
        for item_id, qty_before in items_before.items():
            qty_after = items_after.get(item_id, 0)
            lost = qty_before - qty_after
            if lost <= 0:
                continue
            res = await session.execute(
                _sa_select(HouseCustomItem).where(
                    HouseCustomItem.house_id == house.id,
                    HouseCustomItem.item_id == item_id,
                )
            )
            row = res.scalar_one_or_none()
            if row:
                row.quantity = max(0, row.quantity - lost)

    await _apply_battle_item_losses(attacker, att_items_before)
    await _apply_battle_item_losses(defender, def_items_before)
    # commit keyinroq — barcha o'zgarishlar bir session.commit() da saqlanadi

    # Lordlarga roundlarni batafsil yuborish
    lord_ids = [lid for lid in [attacker.lord_id, defender.lord_id] if lid]

    # Boshlang'ich holat xabari
    from database.repositories import CustomItemRepo as _CIRepo
    _ci_repo = _CIRepo(session)
    att_ci = await _ci_repo.get_house_items_with_info(attacker.id)
    def_ci = await _ci_repo.get_house_items_with_info(defender.id)

    def _fmt_items(items):
        if not items:
            return ""
        return " | " + " ".join(f"{r.item.emoji}{r.item.name}×{r.quantity}" for r in items)

    intro = (
        f"⚔️ <b>JANG BOSHLANDI!</b>\n\n"
        f"🔴 <b>{attacker.name}</b>: {attacker.total_soldiers} askar | "
        f"{attacker.total_dragons} ajdar | {attacker.total_scorpions} skorpion"
        f"{_fmt_items(att_ci)}\n"
        f"🔵 <b>{defender.name}</b>: {defender.total_soldiers} askar | "
        f"{defender.total_dragons} ajdar | {defender.total_scorpions} skorpion"
        f"{_fmt_items(def_ci)}"
    )
    if attacker_allies:
        intro += "\n🤝 Hujumchi ittifoqchilari: " + ", ".join(a.house_name for a in attacker_allies)
    if defender_allies:
        intro += "\n🤝 Mudofaachi ittifoqchilari: " + ", ".join(a.house_name for a in defender_allies)

    for lord_id in lord_ids:
        try:
            await bot.send_message(lord_id, intro, parse_mode="HTML")
        except Exception:
            pass

    # Har bir roundni alohida yuborish
    for rnd in result.round_results:
        round_text = "\n".join(rnd.log).strip()
        if not round_text:
            continue
        for lord_id in lord_ids:
            try:
                await bot.send_message(lord_id, round_text, parse_mode="HTML")
            except Exception:
                pass

    # G'olibga o'lja berish
    if result.attacker_wins:
        await house_repo.update_treasury(attacker.id, result.loot_gold)
        await house_repo.update_treasury(defender.id, -min(result.loot_gold, defender.treasury))
        await house_repo.update_military(attacker.id,
            soldiers=-result.attacker_soldiers_lost + result.loot_soldiers,
            dragons=-result.attacker_dragons_lost + result.loot_dragons,
            scorpions=-result.attacker_scorpions_lost,
        )
        await house_repo.update_military(defender.id,
            soldiers=-result.defender_soldiers_lost - result.loot_soldiers,
            dragons=-result.defender_dragons_lost - result.loot_dragons,
            scorpions=-result.defender_scorpions_lost,
        )
        # Custom itemlar o'ljasi — g'olib (attacker) yutilgan (defender) itemlarining 51% ini oladi
        await _transfer_custom_item_loot(
            session, loser_id=defender.id, winner_id=attacker.id
        )
        # Agar attacker avval defender vassali bo'lgan bo'lsa — ozod bo'ladi
        if attacker.is_under_occupation and attacker.occupier_house_id == defender.id:
            await house_repo.clear_occupation(attacker.id)
        # Defender vassal bo'ladi — o'lpon tizimi uchun
        await house_repo.set_occupation(defender.id, attacker.id, tax_rate=0.10)
        await _handle_lord_succession(session, war, bot)
    else:
        await house_repo.update_treasury(defender.id, result.loot_gold)
        await house_repo.update_treasury(attacker.id, -min(result.loot_gold, attacker.treasury))
        await house_repo.update_military(attacker.id,
            soldiers=-result.attacker_soldiers_lost - result.loot_soldiers,
            dragons=-result.attacker_dragons_lost - result.loot_dragons,
            scorpions=-result.attacker_scorpions_lost,
        )
        await house_repo.update_military(defender.id,
            soldiers=-result.defender_soldiers_lost + result.loot_soldiers,
            dragons=-result.defender_dragons_lost + result.loot_dragons,
            scorpions=-result.defender_scorpions_lost,
        )
        # Custom itemlar o'ljasi — g'olib (defender) yutilgan (attacker) itemlarining 51% ini oladi
        await _transfer_custom_item_loot(
            session, loser_id=attacker.id, winner_id=defender.id
        )
        # Agar defender avval attacker vassali bo'lgan bo'lsa — ozod bo'ladi
        if defender.is_under_occupation and defender.occupier_house_id == attacker.id:
            await house_repo.clear_occupation(defender.id)
        # Attacker endi defender vassaliga aylanadi
        await house_repo.set_occupation(attacker.id, defender.id, tax_rate=0.10)

    # Ittifoqchi yo'qotmalari
    for house_id, losses in result.attacker_ally_losses.items():
        if losses["soldiers"] > 0 or losses["dragons"] > 0:
            await house_repo.update_military(house_id,
                soldiers=-losses["soldiers"],
                dragons=-losses["dragons"],
                scorpions=-losses.get("scorpions", 0),
            )
    for house_id, losses in result.defender_ally_losses.items():
        if losses["soldiers"] > 0 or losses["dragons"] > 0:
            await house_repo.update_military(house_id,
                soldiers=-losses["soldiers"],
                dragons=-losses["dragons"],
                scorpions=-losses.get("scorpions", 0),
            )

    await war_repo.end_war(
        war.id, result.winner_id, result.loot_gold,
        attacker_soldiers_lost=result.attacker_soldiers_lost,
        defender_soldiers_lost=result.defender_soldiers_lost,
        attacker_dragons_lost=result.attacker_dragons_lost,
        defender_dragons_lost=result.defender_dragons_lost,
    )

    # Yakuniy natija xabari
    winner = attacker if result.winner_id == attacker.id else defender
    loser = defender if result.winner_id == attacker.id else attacker
    final_text = format_chronicle(
        "war_ended",
        winner=winner.name, loser=loser.name,
        loot=result.loot_gold,
        loot_s=result.loot_soldiers,
        loot_d=result.loot_dragons,
        att_lost_s=result.attacker_soldiers_lost,
        att_lost_d=result.attacker_dragons_lost,
        def_lost_s=result.defender_soldiers_lost,
        def_lost_d=result.defender_dragons_lost,
    )
    tg_id = await post_to_chronicle(bot, final_text)
    await chronicle_repo.add("war_ended", final_text, house_id=winner.id, tg_msg_id=tg_id)

    for lord_id in lord_ids:
        try:
            await bot.send_message(lord_id, final_text, parse_mode="HTML")
        except Exception:
            pass

    # Mag'lubning faol omonatiga g'olib flag qo'yish (har kungi foiz bo'linadi)
    from database.repositories import IronBankDepositRepo
    dep_repo = IronBankDepositRepo(session)
    loser_deposit = await dep_repo.get_active(loser.id)
    if loser_deposit:
        await dep_repo.set_war_winner(loser_deposit.id, winner.id)

        loser_lord_id = loser.lord_id
        winner_lord_id = winner.lord_id

        deposit_notice_loser = (
            f"🏦 <b>Omonat foizingiz bo'linadi!</b>\n\n"
            f"⚔️ <b>{winner.name}</b> ga mag'lubiyat sababli\n"
            f"omonatingizdagi <b>har kunlik foizning yarmi</b> ularga o'tib turadi.\n"
            f"Bu omonat muddati tugagunga qadar davom etadi.\n\n"
            f"💡 Yangi omonat ochsangiz bu qoida ta'sir qilmaydi."
        )
        deposit_notice_winner = (
            f"🏦 <b>Omonat foizi bonusi!</b>\n\n"
            f"⚔️ <b>{loser.name}</b> ustidan qozongan g'alabangiz uchun\n"
            f"ularning omonatidagi <b>har kunlik foizning yarmi</b> sizga tushib turadi.\n"
            f"Bu ularning joriy omonati muddati tugagunga qadar davom etadi."
        )

        if loser_lord_id:
            try:
                await bot.send_message(loser_lord_id, deposit_notice_loser, parse_mode="HTML")
            except Exception:
                pass
        if winner_lord_id:
            try:
                await bot.send_message(winner_lord_id, deposit_notice_winner, parse_mode="HTML")
            except Exception:
                pass


# 10 daqiqa eslatma — takroriy yuborishdan saqlash uchun (modul darajasida)
_deploy_reminder_sent: set = set()

DEPLOY_REMINDER_THRESHOLD = 10 * 60  # 600 soniya


async def check_grace_period_job(bot: Bot):
    """Grace Period tugagan urushlarni darhol hisoblash va natijalarni e'lon qilish"""
    from database.repositories import WarDeploymentRepo, HouseRepo
    async with AsyncSessionFactory() as session:
        war_repo  = WarRepo(session)
        active_wars = await war_repo.get_all_active()
        now = datetime.utcnow()

        for war in active_wars:
            if war.status == WarStatusEnum.GRACE_PERIOD and war.grace_ends_at and war.grace_ends_at <= now:
                logger.info(f"Urush #{war.id} grace tugadi — jang boshlanmoqda")
                await war_repo.update_status(war.id, WarStatusEnum.FIGHTING)
                try:
                    await _run_war_v2(war, bot, session)
                except Exception as e:
                    logger.error(f"Urush #{war.id} hisoblashda xato: {e}")

            # 10 daqiqa eslatma — deployment yubormagan lordlarga
            elif (war.status == WarStatusEnum.GRACE_PERIOD
                  and war.grace_ends_at):
                remaining = (war.grace_ends_at - now).total_seconds()
                if 0 < remaining <= DEPLOY_REMINDER_THRESHOLD:
                    dep_repo   = WarDeploymentRepo(session)
                    house_repo = HouseRepo(session)
                    for house_id in [war.attacker_house_id, war.defender_house_id]:
                        reminder_key = f"{war.id}:{house_id}"
                        if reminder_key in _deploy_reminder_sent:
                            continue
                        dep = await dep_repo.get_deployment(war.id, house_id)
                        if not dep:
                            house = await house_repo.get_by_id(house_id)
                            if house and house.lord_id:
                                try:
                                    from keyboards.keyboards import deploy_resources_keyboard
                                    await bot.send_message(
                                        house.lord_id,
                                        f"⚠️ <b>Grace period tugashiga {int(remaining // 60)} daqiqa qoldi!</b>\n\n"
                                        f"Hali resurs yubormadingiz — tez qaror qiling!\n"
                                        f"Resurs yubormagan tomon barcha resursi bilan avtomatik mudofaaga o'tadi.",
                                        reply_markup=deploy_resources_keyboard(war.id),
                                        parse_mode="HTML"
                                    )
                                    _deploy_reminder_sent.add(reminder_key)
                                except Exception as e:
                                    logger.warning(f"Deploy eslatma yuborishda xato (war={war.id}, house={house_id}): {e}")


async def end_war_time_job(bot: Bot):
    """
    23:00 da hali tugamagan urushlarni yakunlash.
    Odatda grace_period_job allaqachon urushlarni tugatkaan bo'ladi,
    bu faqat zaxira sifatida ishlaydi.
    """
    async with AsyncSessionFactory() as session:
        war_repo = WarRepo(session)
        active_wars = await war_repo.get_all_active()

        for war in active_wars:
            if war.status in [WarStatusEnum.FIGHTING, WarStatusEnum.GRACE_PERIOD]:
                logger.info(f"Urush #{war.id} 23:00 da yakunlanmoqda (zaxira)")
                try:
                    await _run_war_v2(war, bot, session)
                except Exception as e:
                    logger.error(f"Urush #{war.id} yakunlashda xato: {e}")


async def _run_war_v2(war, bot, session):
    """
    4-BOSQICH: Deployment tizimi bilan urush hisoblash.
    - WarDeployment bor bo'lsa → faqat deployment resurslari jangga kiradi
    - Deployment yubormagan tomon → auto_defend (barcha mavjud resursi bilan)
    - Hujumchi deployment resurslari allaqachon balansdan ayirilgan (3-bosqich)
    - Mudofaachi auto_defend bo'lsa → eski mantiq (balansdan ayiriladi)
    """
    from utils.battle import calculate_battle, AllyContribution
    from utils.chronicle import post_to_chronicle, format_chronicle
    from database.models import WarAllySupport
    from database.repositories import WarDeploymentRepo, IronBankDepositRepo, CustomItemRepo
    from sqlalchemy import select as sa_select
    from sqlalchemy.orm import selectinload as sa_selectinload
    from dataclasses import dataclass

    war_repo       = WarRepo(session)
    house_repo     = HouseRepo(session)
    chronicle_repo = ChronicleRepo(session)
    dep_repo_war   = WarDeploymentRepo(session)

    attacker = war.attacker
    defender = war.defender

    # ── Deployment olish ──────────────────────────────────────────────
    att_dep = await dep_repo_war.get_deployment(war.id, attacker.id)
    def_dep = await dep_repo_war.get_deployment(war.id, defender.id)

    # Deployment yubormagan tomon → auto_defend
    if not def_dep:
        await dep_repo_war.set_auto_defend(war.id, defender.id)
        def_dep = await dep_repo_war.get_deployment(war.id, defender.id)
    if not att_dep:
        await dep_repo_war.set_auto_defend(war.id, attacker.id)
        att_dep = await dep_repo_war.get_deployment(war.id, attacker.id)

    att_auto = att_dep.is_auto_defend
    def_auto = def_dep.is_auto_defend

    # ── Omonatdagi resurslarni jangdan chiqarish ──────────────────────
    bank_dep_repo = IronBankDepositRepo(session)
    att_bank = await bank_dep_repo.get_active(attacker.id)
    def_bank = await bank_dep_repo.get_active(defender.id)

    # Auto-defend tomonlar uchun: omonatni chiqarib qo'yish
    if att_auto:
        att_soldiers  = attacker.total_soldiers  - (att_bank.soldiers  if att_bank else 0)
        att_dragons   = attacker.total_dragons   - (att_bank.dragons   if att_bank else 0)
        att_scorpions = attacker.total_scorpions - (att_bank.scorpions if att_bank else 0)
        att_soldiers  = max(0, att_soldiers)
        att_dragons   = max(0, att_dragons)
        att_scorpions = max(0, att_scorpions)
    else:
        # Deployment bor — allaqachon balansdan ayirilgan, deployment qiymati ishlatiladi
        att_soldiers  = att_dep.soldiers
        att_dragons   = att_dep.dragons
        att_scorpions = att_dep.scorpions

    if def_auto:
        def_soldiers  = max(0, defender.total_soldiers  - (def_bank.soldiers  if def_bank else 0))
        def_dragons   = max(0, defender.total_dragons   - (def_bank.dragons   if def_bank else 0))
        def_scorpions = max(0, defender.total_scorpions - (def_bank.scorpions if def_bank else 0))
    else:
        def_soldiers  = def_dep.soldiers
        def_dragons   = def_dep.dragons
        def_scorpions = def_dep.scorpions

    # ── Ittifoqchi yordamlarini yuklash ──────────────────────────────
    ally_result = await session.execute(
        sa_select(WarAllySupport)
        .where(WarAllySupport.war_id == war.id)
        .options(sa_selectinload(WarAllySupport.ally_house))
    )
    ally_supports = ally_result.scalars().all()

    attacker_allies = [
        AllyContribution(
            house_id=s.ally_house_id,
            house_name=s.ally_house.name if s.ally_house else str(s.ally_house_id),
            join_type=s.join_type,
            soldiers=s.soldiers,
            dragons=s.dragons,
            scorpions=s.scorpions,
        )
        for s in ally_supports if s.side == "attacker"
    ]
    defender_allies = [
        AllyContribution(
            house_id=s.ally_house_id,
            house_name=s.ally_house.name if s.ally_house else str(s.ally_house_id),
            join_type=s.join_type,
            soldiers=s.soldiers,
            dragons=s.dragons,
            scorpions=s.scorpions,
        )
        for s in ally_supports if s.side == "defender"
    ]

    # ── Battle uchun vaqtinchalik proxy xonadon obyektlari ───────────
    # calculate_battle() house.total_soldiers/dragons/scorpions ni o'qiydi
    # Deployment qiymatlarini to'g'ridan-to'g'ri o'rnatamiz
    class _HouseProxy:
        def __init__(self, real_house, soldiers, dragons, scorpions):
            self._real = real_house
            self.id               = real_house.id
            self.name             = real_house.name
            self.treasury         = real_house.treasury
            self.total_soldiers   = soldiers
            self.total_dragons    = dragons
            self.total_scorpions  = scorpions
            self.castle_defense   = getattr(real_house, 'castle_defense', 0)
            self._custom_items    = []
            # Boshqa atributlar kerak bo'lsa real_house dan olinadi
        def __getattr__(self, item):
            return getattr(self._real, item)

    att_proxy = _HouseProxy(attacker, att_soldiers, att_dragons, att_scorpions)
    def_proxy = _HouseProxy(defender, def_soldiers, def_dragons, def_scorpions)

    # ── Tashqi urush: garnizon birinchi jangga kiradi ─────────────────
    # Tashqi urush = attacker va defender turli regionda
    from utils.battle import resolve_garrison_battle
    is_external_war = (attacker.region != defender.region)

    garrison_log_lines = []
    if is_external_war:
        garrison_result = await resolve_garrison_battle(
            attacker_name  = attacker.name,
            defender_region= defender.region,
            att_soldiers   = att_soldiers,
            att_dragons    = att_dragons,
            att_scorpions  = att_scorpions,
            session        = session,
        )

        if garrison_result['garrison_exists']:
            # Garnizon xabarlari lordlarga yuboriladi
            garrison_log_lines = garrison_result['log']
            for lord_id in [attacker.lord_id, defender.lord_id]:
                if not lord_id:
                    continue
                try:
                    await bot.send_message(
                        lord_id,
                        "\n".join(garrison_log_lines),
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

            if not garrison_result['garrison_defeated']:
                # Garnizon yengmadi — urush to'xtatiladi, hujumchi chekinadi
                winner_name = defender.name
                loser_name  = attacker.name
                final_text = (
                    f"🏯 <b>Garnizon hujumchini to'xtatdi!</b>\n\n"
                    f"⚔️ {attacker.name} → {defender.name} hujumi\n"
                    f"🔵 {defender.region.value} garnizoni hujumni qaytardi.\n\n"
                    f"🔴 {attacker.name} chekinishga majbur bo'ldi."
                )
                for lord_id in [attacker.lord_id, defender.lord_id]:
                    if not lord_id:
                        continue
                    try:
                        await bot.send_message(lord_id, final_text, parse_mode="HTML")
                    except Exception:
                        pass

                # Hujumchi yo'qotmalarini balansdan ayirish
                att_losses = garrison_result['attacker_losses']
                await house_repo.update_military(
                    attacker.id,
                    soldiers  = -att_losses['soldiers'],
                    dragons   = -att_losses['dragons'],
                    scorpions = -att_losses['scorpions'],
                )
                if not att_auto:
                    # Deployment tirik qolgan askarlarni qaytarish (yo'qotmalardan tashqari)
                    remaining = garrison_result['attacker_remaining']
                    await house_repo.update_military(
                        attacker.id,
                        soldiers  = remaining['soldiers'],
                        dragons   = remaining['dragons'],
                        scorpions = remaining['scorpions'],
                    )

                # Urushni yakunlash — mudofaachi g'olib
                await war_repo.end_war(
                    war.id, defender.id, 0,
                    attacker_soldiers_lost=att_losses['soldiers'],
                    defender_soldiers_lost=0,
                    attacker_dragons_lost=att_losses['dragons'],
                    defender_dragons_lost=0,
                )
                return

            # Garnizon yengildi — hujumchi kamaygan resurslar bilan asosiy jangga kiradi
            remaining = garrison_result['attacker_remaining']
            att_soldiers  = remaining['soldiers']
            att_dragons   = remaining['dragons']
            att_scorpions = remaining['scorpions']
            att_proxy = _HouseProxy(attacker, att_soldiers, att_dragons, att_scorpions)

    # ── Custom itemlar ────────────────────────────────────────────────
    custom_repo = CustomItemRepo(session)
    att_ci_rows = await custom_repo.get_house_items_with_info(attacker.id)
    def_ci_rows = await custom_repo.get_house_items_with_info(defender.id)

    att_items_before = {row.item_id: row.quantity for row in att_ci_rows}
    def_items_before = {row.item_id: row.quantity for row in def_ci_rows}

    att_proxy._custom_items = [{"item": row.item, "qty": row.quantity} for row in att_ci_rows]
    def_proxy._custom_items = [{"item": row.item, "qty": row.quantity} for row in def_ci_rows]

    # ── Hisob-kitob ───────────────────────────────────────────────────
    result = calculate_battle(
        att_proxy, def_proxy,
        defender_gold=defender.treasury,
        attacker_allies=attacker_allies,
        defender_allies=defender_allies,
    )

    # ── Jangda halok bo'lgan itemlar ──────────────────────────────────
    from database.models import HouseCustomItem
    from sqlalchemy import select as _sa_select

    async def _apply_battle_item_losses_v2(house_id, custom_items_list, items_before):
        items_after = {entry["item"].id: entry["qty"] for entry in custom_items_list}
        for item_id, qty_before in items_before.items():
            qty_after = items_after.get(item_id, 0)
            lost = qty_before - qty_after
            if lost <= 0:
                continue
            res = await session.execute(
                _sa_select(HouseCustomItem).where(
                    HouseCustomItem.house_id == house_id,
                    HouseCustomItem.item_id == item_id,
                )
            )
            row = res.scalar_one_or_none()
            if row:
                row.quantity = max(0, row.quantity - lost)

    await _apply_battle_item_losses_v2(attacker.id, att_proxy._custom_items, att_items_before)
    await _apply_battle_item_losses_v2(defender.id, def_proxy._custom_items, def_items_before)

    # ── Lordlarga round xabarlari ─────────────────────────────────────
    lord_ids = [lid for lid in [attacker.lord_id, defender.lord_id] if lid]

    def _fmt_items(rows):
        if not rows:
            return ""
        return " | " + " ".join(f"{r.item.emoji}{r.item.name}×{r.quantity}" for r in rows)

    att_mode = "🛡️ Avtomatik" if att_auto else "🗡️ Deployment"
    def_mode = "🛡️ Avtomatik" if def_auto else "🗡️ Deployment"

    intro = (
        f"⚔️ <b>JANG BOSHLANDI!</b>\n\n"
        f"🔴 <b>{attacker.name}</b> [{att_mode}]: {att_soldiers} askar | "
        f"{att_dragons} ajdar | {att_scorpions} skorpion"
        f"{_fmt_items(att_ci_rows)}\n"
        f"🔵 <b>{defender.name}</b> [{def_mode}]: {def_soldiers} askar | "
        f"{def_dragons} ajdar | {def_scorpions} skorpion"
        f"{_fmt_items(def_ci_rows)}"
    )
    if attacker_allies:
        intro += "\n🤝 Hujumchi ittifoqchilari: " + ", ".join(a.house_name for a in attacker_allies)
    if defender_allies:
        intro += "\n🤝 Mudofaachi ittifoqchilari: " + ", ".join(a.house_name for a in defender_allies)

    for lord_id in lord_ids:
        try:
            await bot.send_message(lord_id, intro, parse_mode="HTML")
        except Exception:
            pass

    for rnd in result.round_results:
        round_text = "\n".join(rnd.log).strip()
        if not round_text:
            continue
        for lord_id in lord_ids:
            try:
                await bot.send_message(lord_id, round_text, parse_mode="HTML")
            except Exception:
                pass

    # ── Resurs yo'qotmalari va o'lja ─────────────────────────────────
    if result.attacker_wins:
        # Hujumchi g'alaba — o'lja oladi
        await house_repo.update_treasury(attacker.id, result.loot_gold)
        await house_repo.update_treasury(defender.id, -min(result.loot_gold, defender.treasury))

        if att_auto:
            # Auto-defend hujumchi: yo'qotmalar balansdan ayiriladi
            await house_repo.update_military(attacker.id,
                soldiers=-result.attacker_soldiers_lost + result.loot_soldiers,
                dragons=-result.attacker_dragons_lost  + result.loot_dragons,
                scorpions=-result.attacker_scorpions_lost,
            )
        else:
            # Deployment hujumchi: resurslar allaqachon ayirilgan
            # Tirik qolganlar (deployed - lost) + o'lja qaytariladi
            att_survivors_s  = att_soldiers  - result.attacker_soldiers_lost
            att_survivors_d  = att_dragons   - result.attacker_dragons_lost
            att_survivors_sc = att_scorpions - result.attacker_scorpions_lost
            await house_repo.update_military(attacker.id,
                soldiers=att_survivors_s  + result.loot_soldiers,
                dragons=att_survivors_d   + result.loot_dragons,
                scorpions=att_survivors_sc,
            )

        if def_auto:
            # Auto-defend mudofaachi: yo'qotmalar balansdan ayiriladi
            await house_repo.update_military(defender.id,
                soldiers=-result.defender_soldiers_lost - result.loot_soldiers,
                dragons=-result.defender_dragons_lost  - result.loot_dragons,
                scorpions=-result.defender_scorpions_lost,
            )
        else:
            # Deployment mudofaachi: resurslar allaqachon ayirilgan
            # Tirik qolganlardan o'lja chiqariladi, qolgan qaytariladi
            def_survivors_s  = def_soldiers  - result.defender_soldiers_lost
            def_survivors_d  = def_dragons   - result.defender_dragons_lost
            def_survivors_sc = def_scorpions - result.defender_scorpions_lost
            await house_repo.update_military(defender.id,
                soldiers=def_survivors_s  - result.loot_soldiers,
                dragons=def_survivors_d   - result.loot_dragons,
                scorpions=def_survivors_sc,
            )

        await _transfer_custom_item_loot(session, loser_id=defender.id, winner_id=attacker.id)
        if attacker.is_under_occupation and attacker.occupier_house_id == defender.id:
            await house_repo.clear_occupation(attacker.id)
        await house_repo.set_occupation(defender.id, attacker.id, tax_rate=0.10)
        await _handle_lord_succession(session, war, bot)
    else:
        # Mudofaachi g'alaba
        await house_repo.update_treasury(defender.id, result.loot_gold)
        await house_repo.update_treasury(attacker.id, -min(result.loot_gold, attacker.treasury))

        if att_auto:
            await house_repo.update_military(attacker.id,
                soldiers=-result.attacker_soldiers_lost - result.loot_soldiers,
                dragons=-result.attacker_dragons_lost  - result.loot_dragons,
                scorpions=-result.attacker_scorpions_lost,
            )
        else:
            # Deployment hujumchi yutqazdi — resurslar allaqachon ayirilgan
            # Tirik qolganlardan o'lja chiqariladi, qolgan qaytariladi
            att_survivors_s  = att_soldiers  - result.attacker_soldiers_lost
            att_survivors_d  = att_dragons   - result.attacker_dragons_lost
            att_survivors_sc = att_scorpions - result.attacker_scorpions_lost
            await house_repo.update_military(attacker.id,
                soldiers=att_survivors_s  - result.loot_soldiers,
                dragons=att_survivors_d   - result.loot_dragons,
                scorpions=att_survivors_sc,
            )

        if def_auto:
            await house_repo.update_military(defender.id,
                soldiers=-result.defender_soldiers_lost + result.loot_soldiers,
                dragons=-result.defender_dragons_lost  + result.loot_dragons,
                scorpions=-result.defender_scorpions_lost,
            )
        else:
            # Deployment mudofaachi yutdi — resurslar allaqachon ayirilgan
            # Tirik qolganlar (deployed - lost) + o'lja qaytariladi
            def_survivors_s  = def_soldiers  - result.defender_soldiers_lost
            def_survivors_d  = def_dragons   - result.defender_dragons_lost
            def_survivors_sc = def_scorpions - result.defender_scorpions_lost
            await house_repo.update_military(defender.id,
                soldiers=def_survivors_s  + result.loot_soldiers,
                dragons=def_survivors_d   + result.loot_dragons,
                scorpions=def_survivors_sc,
            )

        await _transfer_custom_item_loot(session, loser_id=attacker.id, winner_id=defender.id)
        if defender.is_under_occupation and defender.occupier_house_id == attacker.id:
            await house_repo.clear_occupation(defender.id)
        await house_repo.set_occupation(attacker.id, defender.id, tax_rate=0.10)

    # ── Ittifoqchi yo'qotmalari ───────────────────────────────────────
    for house_id, losses in result.attacker_ally_losses.items():
        if losses["soldiers"] > 0 or losses["dragons"] > 0:
            await house_repo.update_military(house_id,
                soldiers=-losses["soldiers"],
                dragons=-losses["dragons"],
                scorpions=-losses.get("scorpions", 0),
            )
    for house_id, losses in result.defender_ally_losses.items():
        if losses["soldiers"] > 0 or losses["dragons"] > 0:
            await house_repo.update_military(house_id,
                soldiers=-losses["soldiers"],
                dragons=-losses["dragons"],
                scorpions=-losses.get("scorpions", 0),
            )

    await war_repo.end_war(
        war.id, result.winner_id, result.loot_gold,
        attacker_soldiers_lost=result.attacker_soldiers_lost,
        defender_soldiers_lost=result.defender_soldiers_lost,
        attacker_dragons_lost=result.attacker_dragons_lost,
        defender_dragons_lost=result.defender_dragons_lost,
    )

    # ── Yakuniy natija xabari ─────────────────────────────────────────
    winner = attacker if result.winner_id == attacker.id else defender
    loser  = defender if result.winner_id == attacker.id else attacker
    final_text = format_chronicle(
        "war_ended",
        winner=winner.name, loser=loser.name,
        loot=result.loot_gold,
        loot_s=result.loot_soldiers,
        loot_d=result.loot_dragons,
        att_lost_s=result.attacker_soldiers_lost,
        att_lost_d=result.attacker_dragons_lost,
        def_lost_s=result.defender_soldiers_lost,
        def_lost_d=result.defender_dragons_lost,
    )
    tg_id = await post_to_chronicle(bot, final_text)
    await chronicle_repo.add("war_ended", final_text, house_id=winner.id, tg_msg_id=tg_id)

    for lord_id in lord_ids:
        try:
            await bot.send_message(lord_id, final_text, parse_mode="HTML")
        except Exception:
            pass

    # ── Asirga olish imkoni ───────────────────────────────────────────
    from keyboards.keyboards import capture_lord_keyboard
    winner_house = attacker if result.attacker_wins else defender
    loser_house  = defender if result.attacker_wins else attacker

    if winner_house.lord_id and loser_house.lord_id:
        try:
            await bot.send_message(
                winner_house.lord_id,
                f"⚔️ <b>Mag'lub lordni asirga olasizmi?</b>\n\n"
                f"👤 {loser_house.name} lording\n"
                f"💰 Narxi: 100 askar\n"
                f"📦 Asir lordning barcha resurslari (omonatdan tashqari) sizga o'tadi.",
                reply_markup=capture_lord_keyboard(war.id, loser_house.lord_id),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Asirga olish tugmasi yuborishda xato: {e}")

    # ── Omonat: g'olibga flag qo'yish ────────────────────────────────
    bank_dep_repo2 = IronBankDepositRepo(session)
    loser_deposit = await bank_dep_repo2.get_active(loser.id)
    if loser_deposit:
        await bank_dep_repo2.set_war_winner(loser_deposit.id, winner.id)

        deposit_notice_loser = (
            f"🏦 <b>Omonat foizingiz bo'linadi!</b>\n\n"
            f"Urushda mag'lub bo'ldingiz — omonat foizingizning bir qismi "
            f"<b>{winner.name}</b> xonadoniga o'tadi.\n"
            f"Foiz bo'linishi har kuni soat 02:00 da amalga oshiriladi."
        )
        deposit_notice_winner = (
            f"🏦 <b>Dushman omonatidan foiz olasiz!</b>\n\n"
            f"<b>{loser.name}</b> xonadonining omonat foizi "
            f"har kuni sizga o'tkaziladi."
        )
        if loser.lord_id:
            try:
                await bot.send_message(loser.lord_id, deposit_notice_loser, parse_mode="HTML")
            except Exception:
                pass
        if winner.lord_id:
            try:
                await bot.send_message(winner.lord_id, deposit_notice_winner, parse_mode="HTML")
            except Exception:
                pass


async def _handle_lord_succession(session, war, bot):
    """
    Attacker yutganda rol o'tishi:
    - Agar defender HIGH_LORD bo'lsa → defender LORD ga tushiriladi
    - Agar attacker shu hududda defender o'rnini egallasa → attacker HIGH_LORD bo'ladi
    """
    from database.models import House, User, RoleEnum
    from sqlalchemy import select

    # Defender va attacker xonadonlarini olish
    defender_result = await session.execute(
        select(House).where(House.id == war.defender_house_id)
    )
    defender_house = defender_result.scalar_one_or_none()

    attacker_result = await session.execute(
        select(House).where(House.id == war.attacker_house_id)
    )
    attacker_house = attacker_result.scalar_one_or_none()

    if not defender_house or not attacker_house:
        return

    # Agar defender HIGH_LORD bo'lsa — unvonini olib, LORD qilamiz
    if defender_house.high_lord_id:
        old_high_lord_user_id = defender_house.high_lord_id
        defender_house.high_lord_id = None

        # Foydalanuvchi rolini HIGH_LORD dan LORD ga tushirish
        await session.execute(
            update(User)
            .where(
                User.id == old_high_lord_user_id,
                User.role == RoleEnum.HIGH_LORD
            )
            .values(role=RoleEnum.LORD)
        )

        # Defender lordiga xabar
        if defender_house.lord_id:
            try:
                await bot.send_message(
                    defender_house.lord_id,
                    f"👑 <b>HUKMDORLIK YO'QOLDI!</b>\n\n"
                    f"Siz jangda mag'lub bo'ldingiz va "
                    f"<b>{defender_house.region.value}</b> hududidagi "
                    f"Hukmdorlik unvoningizni yo'qotdingiz.\n"
                    f"Xonadoningiz endi vassal maqomida.",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        # Attacker xonadonini HIGH_LORD qilish (faqat bir xududda bo'lsa)
        # Attacker defender bilan bir hududda bo'lishi kerak
        if attacker_house.region == defender_house.region and attacker_house.lord_id:
            attacker_house.high_lord_id = attacker_house.lord_id

            await session.execute(
                update(User)
                .where(User.id == attacker_house.lord_id)
                .values(role=RoleEnum.HIGH_LORD)
            )

            # Hududdagi boshqa xonadonlarning HIGH_LORD unvonini bekor qilish
            region_result = await session.execute(
                select(House).where(
                    House.region == attacker_house.region,
                    House.id != attacker_house.id,
                )
            )
            region_houses = region_result.scalars().all()
            for rh in region_houses:
                if rh.high_lord_id:
                    rh.high_lord_id = None
                    if rh.lord_id:
                        await session.execute(
                            update(User)
                            .where(
                                User.id == rh.lord_id,
                                User.role == RoleEnum.HIGH_LORD
                            )
                            .values(role=RoleEnum.LORD)
                        )

            try:
                await bot.send_message(
                    attacker_house.lord_id,
                    f"👑 <b>SIZ HUKMDOR BO'LDINGIZ!</b>\n\n"
                    f"Jangda g'alaba qozonib, <b>{defender_house.region.value}</b> "
                    f"hududining <b>HUKMDORI</b> bo'ldingiz!\n"
                    f"Barcha vassal xonadonlar sizga o'lpon to'laydi.",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    await session.commit()





async def reload_farm_jobs(bot):
    """Admin farm jadvalini o'zgartirganda schedulerni qayta yuklash"""
    global_scheduler = get_global_scheduler()
    async with AsyncSessionFactory() as session:
        from database.repositories import BotSettingsRepo
        cfg = BotSettingsRepo(session)
        farm_schedules = await cfg.get_farm_schedules()

    # Eski farm joblarini o'chirish
    for job in global_scheduler.get_jobs():
        if job.id.startswith("daily_farm_"):
            global_scheduler.remove_job(job.id)

    # Yangilarini qo'shish — vaqt Toshkent (UTC+5) da berilgan
    for i, sched in enumerate(farm_schedules):
        global_scheduler.add_job(
            daily_farm_job,
            CronTrigger(hour=sched["hour"], minute=sched["minute"], timezone="Asia/Tashkent"),
            args=[bot, sched["amount"]],
            id=f"daily_farm_{i}",
            replace_existing=True,
        )
        logger.info(f"Farm job qayta yuklandi #{i}: {sched['hour']:02d}:{sched['minute']:02d} Tashkent — {sched['amount']} tanga")


async def setup_scheduler(scheduler: AsyncIOScheduler, bot: Bot):
    # Kunlik farm — DB dan dinamik jadval o'qish
    async with AsyncSessionFactory() as session:
        from database.repositories import BotSettingsRepo
        cfg = BotSettingsRepo(session)
        farm_schedules = await cfg.get_farm_schedules()

    # Eski farm joblarini tozalash
    for job in scheduler.get_jobs():
        if job.id.startswith("daily_farm_"):
            scheduler.remove_job(job.id)

    # Yangi farm jadvallarini qo'shish — vaqt Toshkent (UTC+5) da
    for i, sched in enumerate(farm_schedules):
        scheduler.add_job(
            daily_farm_job,
            CronTrigger(hour=sched["hour"], minute=sched["minute"], timezone="Asia/Tashkent"),
            args=[bot, sched["amount"]],
            id=f"daily_farm_{i}",
            replace_existing=True,
        )
        logger.info(f"Farm job #{i}: {sched['hour']:02d}:{sched['minute']:02d} Tashkent — {sched['amount']} tanga")

    if not farm_schedules:
        # Default agar jadval bo'sh bo'lsa — Toshkent 08:00
        scheduler.add_job(
            daily_farm_job,
            CronTrigger(hour=8, minute=0, timezone="Asia/Tashkent"),
            args=[bot, 50],
            id="daily_farm_0",
            replace_existing=True,
        )

    # Grace period tekshiruvi - har 5 daqiqada
    scheduler.add_job(
        check_grace_period_job,
        "interval",
        minutes=5,
        args=[bot],
        id="grace_check",
        replace_existing=True,
    )

    # Urush tugashi - har kuni 23:00 Toshkent
    scheduler.add_job(
        end_war_time_job,
        CronTrigger(hour=23, minute=0, timezone="Asia/Tashkent"),
        args=[bot],
        id="war_end",
        replace_existing=True,
    )

    # Civil urushlar tugashini tekshirish - har 10 daqiqada
    scheduler.add_job(
        check_civil_wars_job,
        "interval",
        minutes=10,
        args=[bot],
        id="civil_wars_check",
        replace_existing=True,
    )

    # Da'vo muddati tugashini tekshirish (1 soat javob bermaganlar) - har 15 daqiqada
    scheduler.add_job(
        check_claim_timeouts_job,
        "interval",
        minutes=15,
        args=[bot],
        id="claim_timeout_check",
        replace_existing=True,
    )

    # Omonat: kunlik foiz + muddat tugaganlarni yopish — vaqt DB dan olinadi
    async with AsyncSessionFactory() as session:
        from database.repositories import BotSettingsRepo as _BSR
        _cfg = _BSR(session)
        dep_hour   = await _cfg.get_int("deposit_job_hour")
        dep_minute = await _cfg.get_int("deposit_job_minute")

    scheduler.add_job(
        process_deposits_job,
        CronTrigger(hour=dep_hour, minute=dep_minute, timezone="Asia/Tashkent"),
        args=[bot],
        id="deposit_check",
        replace_existing=True,
    )
    logger.info(f"Deposit job: har kuni {dep_hour:02d}:{dep_minute:02d} Tashkent")

    logger.info("Scheduler jobs o'rnatildi")


async def check_civil_wars_job(bot: Bot):
    """Civil urushlar tugashini tekshirib, Hukmdorni belgilash"""
    from handlers.claim import check_claim_wars_ended
    async with AsyncSessionFactory() as session:
        await check_claim_wars_ended(bot, session)


async def check_claim_timeouts_job(bot: Bot):
    """1 soat ichida javob bermagan xonadonlarga avtomatik urush boshlash"""
    from database.models import HukmdorClaim, ClaimStatusEnum, WarTypeEnum
    from database.repositories import HukmdorClaimRepo, HouseRepo, WarRepo
    from sqlalchemy import select
    from datetime import datetime, timedelta

    async with AsyncSessionFactory() as session:
        claim_repo = HukmdorClaimRepo(session)
        house_repo = HouseRepo(session)
        war_repo = WarRepo(session)

        now = datetime.utcnow()

        # PENDING da'volar — 1 soat o'tgan, javob bermaganlarni rad etib urush boshlash
        result = await session.execute(
            select(HukmdorClaim).where(HukmdorClaim.status == ClaimStatusEnum.PENDING)
        )
        pending_claims = result.scalars().all()

        for claim in pending_claims:
            if (now - claim.created_at).total_seconds() < 3600:
                continue

            responses = await claim_repo.get_all_responses(claim.id)
            claimant = await house_repo.get_by_id(claim.claimant_house_id)
            has_rejection = False

            for resp in responses:
                if resp.accepted is True:
                    continue
                if resp.accepted is False:
                    has_rejection = True
                    continue

                # Javob bermagan — avtomatik rad
                await claim_repo.set_response(claim.id, resp.house_id, accepted=False)
                has_rejection = True
                defender = await house_repo.get_by_id(resp.house_id)

                if defender and defender.lord_id:
                    try:
                        await bot.send_message(
                            defender.lord_id,
                            f"⏰ <b>Muddati o'tdi!</b>\n\n"
                            f"<b>{claimant.name}</b> xonadonining hukmdorlik da'vosiga "
                            f"javob bermaganligi sababli urush boshlanmoqda!",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass

                # Civil urush darhol — vaqtga bog'liq emas
                active = await war_repo.get_active_war(resp.house_id)
                if not active:
                    grace_ends = now + timedelta(minutes=settings.GRACE_PERIOD_MINUTES)
                    war = await war_repo.create_war(claimant.id, resp.house_id, grace_ends)
                    from sqlalchemy import update
                    from database.models import War
                    await session.execute(
                        update(War).where(War.id == war.id).values(
                            war_type=WarTypeEnum.CIVIL.value,
                            claim_id=claim.id,
                        )
                    )
                    if claimant and claimant.lord_id:
                        try:
                            await bot.send_message(
                                claimant.lord_id,
                                f"⚔️ <b>{defender.name if defender else '?'}</b> javob bermadi — "
                                f"urush boshlanmoqda!\n"
                                f"Grace Period: {settings.GRACE_PERIOD_MINUTES} daqiqa",
                                parse_mode="HTML"
                            )
                        except Exception:
                            pass

            if has_rejection:
                await claim_repo.set_status(claim.id, ClaimStatusEnum.IN_PROGRESS)
            else:
                # Hamma qabul qildi
                await claim_repo.set_status(claim.id, ClaimStatusEnum.COMPLETED)
                await claim_repo.resolve_hukmdor(claim.region, claim.claimant_house_id, bot)

            await session.commit()


async def process_deposits_job(bot: Bot):
    """Kunlik foiz to'lash + muddat tugagan omonatlarni avtomatik yopish"""
    from database.repositories import IronBankDepositRepo
    from database.models import IronBankDeposit
    from config.settings import settings as cfg

    logger.info("Omonat tekshiruvi boshlandi...")

    # Barcha faol omonat ID larini olish
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(IronBankDeposit).where(IronBankDeposit.is_active == True)
        )
        dep_ids = [d.id for d in result.scalars().all()]

    logger.info(f"Faol omonatlar: {len(dep_ids)} ta")

    for dep_id in dep_ids:
        try:
            async with AsyncSessionFactory() as session:
                result = await session.execute(
                    select(IronBankDeposit).where(
                        IronBankDeposit.id == dep_id,
                        IronBankDeposit.is_active == True
                    )
                )
                dep = result.scalar_one_or_none()
                if not dep:
                    continue

                dep_repo = IronBankDepositRepo(session)
                house_repo = HouseRepo(session)
                now = datetime.utcnow()

                # Joriy bozor narxlari
                from database.repositories import MarketRepo
                market_repo = MarketRepo(session)
                prices = await market_repo.get_all_prices()
                s_price  = prices.get("soldier",  cfg.SOLDIER_PRICE)
                d_price  = prices.get("dragon",   cfg.DRAGON_PRICE)
                sc_price = prices.get("scorpion", cfg.SCORPION_PRICE)

                if now >= dep.expires_at:
                    # Muddat tugadi — yopish
                    interest = await dep_repo.close(dep, pay_interest=True,
                                                    s_price=s_price, d_price=d_price, sc_price=sc_price)
                    logger.info(f"Omonat #{dep_id} yopildi. Foiz: {interest}")
                    house = await house_repo.get_by_id(dep.house_id)
                    if house and house.lord_id:
                        try:
                            await bot.send_message(
                                house.lord_id,
                                f"🏦 <b>Omonat muddati tugadi!</b>\n\n"
                                f"💰 Oltin qaytarildi: {dep.gold:,} tanga\n"
                                f"🗡️ Askarlar: {dep.soldiers:,}\n"
                                f"🐉 Ajdarlar: {dep.dragons:,}\n"
                                f"🏹 Skorpionlar: {dep.scorpions:,}\n"
                                f"📈 Foiz daromadi: +{interest:,} tanga\n\n"
                                f"✅ Barcha resurslar xazinangizga qaytarildi!",
                                parse_mode="HTML"
                            )
                        except Exception:
                            pass
                else:
                    # Kunlik foiz to'lash
                    interest, winner_share = await dep_repo.pay_daily_interest(dep,
                                                                               s_price=s_price, d_price=d_price, sc_price=sc_price)
                    logger.info(f"Omonat #{dep_id} kunlik foiz: +{interest} (g'olib ulushi: {winner_share})")
                    if interest > 0:
                        house = await house_repo.get_by_id(dep.house_id)
                        days_left = max(0, (dep.expires_at - now).days)
                        mil_val = dep.soldiers * s_price + dep.dragons * d_price + dep.scorpions * sc_price
                        loser_share = interest - winner_share

                        # Mag'lubga xabar
                        if house and house.lord_id:
                            loser_msg = (
                                f"🏦 <b>Omonat kunlik foizi keldi!</b>\n\n"
                                f"📊 Omonat: {dep.gold + mil_val:,} tanga (umumiy)\n"
                                f"📈 Kunlik foiz: {interest:,} tanga\n"
                            )
                            if winner_share > 0:
                                loser_msg += (
                                    f"💸 Sizga: <b>{loser_share:,} tanga</b> (yarmi urush g'olibiga ketdi)\n"
                                )
                            else:
                                loser_msg += f"💰 Sizga: <b>{interest:,} tanga</b>\n"
                            loser_msg += f"⏳ Omonat tugashiga: {days_left} kun"
                            try:
                                await bot.send_message(house.lord_id, loser_msg, parse_mode="HTML")
                            except Exception:
                                pass

                        # G'olibga xabar (agar flag bo'lsa)
                        if winner_share > 0 and dep.war_winner_house_id:
                            winner_house = await house_repo.get_by_id(dep.war_winner_house_id)
                            if winner_house and winner_house.lord_id:
                                try:
                                    await bot.send_message(
                                        winner_house.lord_id,
                                        f"🏦 <b>Omonat foizi bonusi keldi!</b>\n\n"
                                        f"⚔️ <b>{house.name if house else ''}</b> omonatidan\n"
                                        f"💰 <b>+{winner_share:,} tanga</b> xazinangizga tushdi",
                                        parse_mode="HTML"
                                    )
                                except Exception:
                                    pass
        except Exception as e:
            logger.error(f"Omonat #{dep_id} tekshiruvida xato: {e}")

    logger.info("Omonat tekshiruvi yakunlandi.")
