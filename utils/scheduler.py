from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot
from database.engine import AsyncSessionFactory
from database.repositories import UserRepo, HouseRepo, WarRepo, IronBankRepo, ChronicleRepo
from database.models import RoleEnum, WarStatusEnum
from sqlalchemy import select, update
from database.models import User, House
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Global scheduler referensini saqlash uchun — circular import muammosini hal qiladi
_global_scheduler: AsyncIOScheduler | None = None


def set_global_scheduler(scheduler: AsyncIOScheduler):
    """main.py dan scheduler o'rnatilganda chaqiriladi"""
    global _global_scheduler
    _global_scheduler = scheduler


def get_global_scheduler() -> AsyncIOScheduler:
    if _global_scheduler is None:
        raise RuntimeError("Scheduler hali o'rnatilmagan. set_global_scheduler() chaqiring.")
    return _global_scheduler


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
            soldiers=-result.attacker_soldiers_lost,
            dragons=-result.attacker_dragons_lost,
            scorpions=-result.attacker_scorpions_lost,
        )
        await house_repo.update_military(defender.id,
            soldiers=-result.defender_soldiers_lost,
            dragons=-result.defender_dragons_lost,
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
            soldiers=-result.attacker_soldiers_lost,
            dragons=-result.attacker_dragons_lost,
            scorpions=-result.attacker_scorpions_lost,
        )
        await house_repo.update_military(defender.id,
            soldiers=-result.defender_soldiers_lost,
            dragons=-result.defender_dragons_lost,
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


async def check_grace_period_job(bot: Bot):
    """Grace Period tugagan urushlarni darhol hisoblash va natijalarni e'lon qilish"""
    async with AsyncSessionFactory() as session:
        war_repo = WarRepo(session)
        active_wars = await war_repo.get_all_active()
        now = datetime.utcnow()

        for war in active_wars:
            if war.status == WarStatusEnum.GRACE_PERIOD and war.grace_ends_at and war.grace_ends_at <= now:
                logger.info(f"Urush #{war.id} grace tugadi — jang boshlanmoqda")
                await war_repo.update_status(war.id, WarStatusEnum.FIGHTING)
                try:
                    await _run_war(war, bot, session)
                except Exception as e:
                    logger.error(f"Urush #{war.id} hisoblashda xato: {e}")


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
                    await _run_war(war, bot, session)
                except Exception as e:
                    logger.error(f"Urush #{war.id} yakunlashda xato: {e}")


async def _handle_lord_succession(session, war, bot):
    """Mag'lub lord almashishi"""
    from database.repositories import UserRepo, HouseRepo
    from database.models import RoleEnum
    user_repo = UserRepo(session)
    house_repo = HouseRepo(session)

    defender = war.defender
    if not defender.lord_id:
        return

    old_lord = await user_repo.get_by_id(defender.lord_id)
    if not old_lord:
        return

    # Yangi lord topish
    new_lord = await user_repo.get_most_active_member(defender.id, old_lord.id)

    # Eski lordni surgun qilish
    attacker = war.attacker
    await user_repo.exile_user(old_lord, attacker.id)

    if new_lord:
        new_lord.role = RoleEnum.LORD
        defender.lord_id = new_lord.id
        await session.commit()

        try:
            await bot.send_message(
                new_lord.id,
                f"👑 <b>Tabriklaymiz!</b>\nSiz <b>{defender.name}</b> xonadonining yangi Lordi bo'ldingiz!\n"
                f"Sobiq lord surgun qilindi.",
                parse_mode="HTML"
            )
        except Exception:
            pass
    else:
        # G'olib o'z odamini tayinlaydi (lord_id = None qoladi, keyingi /start da to'ldiriladi)
        defender.lord_id = None
        await session.commit()


async def check_iron_bank_debt_job(bot: Bot):
    """Har kuni qarzni tekshirish, muddati o'tganlarga jazo berish"""
    from database.repositories import IronBankRepo, UserRepo, HouseRepo
    from sqlalchemy import select
    from database.models import IronBankLoan

    async with AsyncSessionFactory() as session:
        now = datetime.utcnow()
        result = await session.execute(
            select(IronBankLoan).where(
                IronBankLoan.paid == False,
                IronBankLoan.due_date <= now,
            )
        )
        overdue = result.scalars().all()

        iron_bank_repo = IronBankRepo(session)
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)

        # Bir xonadonga bir marta musodara — house_id bo'yicha deduplikatsiya
        processed_houses = set()

        for loan in overdue:
            user = await user_repo.get_by_id(loan.user_id)
            if not user or not user.house_id:
                continue
            if user.house_id in processed_houses:
                continue

            house_debt = await iron_bank_repo.get_house_active_debt(user.house_id)
            if house_debt <= 0:
                continue

            processed_houses.add(user.house_id)
            await iron_bank_repo.confiscate_for_debt(user)

            house = await house_repo.get_by_id(user.house_id)
            house_name = house.name if house else "Xonadon"

            # Xonadonning barcha a'zolariga xabar
            members = await user_repo.get_house_members(user.house_id)
            for member in members:
                try:
                    await bot.send_message(
                        member.id,
                        f"🏦 <b>TEMIR BANK MUSODARA!</b>\n\n"
                        f"🏰 <b>{house_name}</b> xonadonining qarzi muddati o'tdi.\n"
                        f"Barcha qo'shin, ajdar, skorpion va maxsus qurollar musodara qilindi!",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

        logger.info(f"Temir Bank tekshiruvi: {len(processed_houses)} ta xonadon musodara qilindi")


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

    # Temir Bank tekshiruvi - har kuni 00:00 Toshkent
    scheduler.add_job(
        check_iron_bank_debt_job,
        CronTrigger(hour=0, minute=0, timezone="Asia/Tashkent"),
        args=[bot],
        id="iron_bank_check",
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
