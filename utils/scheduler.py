from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot
from database.engine import AsyncSessionFactory
from database.repositories import UserRepo, HouseRepo, WarRepo, IronBankRepo, ChronicleRepo
from database.models import RoleEnum, WarStatusEnum
from sqlalchemy import select, update
from database.models import User
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


async def daily_farm_job(bot: Bot, scheduled_amount: int = 0):
    """Kunlik farm: jadval bo'yicha belgilangan miqdorni xonadon xazinasiga qo'shadi"""
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)

        result = await session.execute(select(User).where(User.is_active == True))
        all_users = result.scalars().all()

        # Har xonadon bo'yicha farm summani hisoblash
        house_farm: dict[int, int] = {}
        for user in all_users:
            if user.role == RoleEnum.ADMIN or not user.house_id:
                continue
            if scheduled_amount > 0:
                # Admin tomonidan belgilangan miqdor — hamma uchun bir xil
                amount = scheduled_amount
            else:
                amount = 50 if user.role in [RoleEnum.HIGH_LORD, RoleEnum.LORD] else 20
            house_farm[user.house_id] = house_farm.get(user.house_id, 0) + amount

        # Xazinalarga qo'shish
        for house_id, total in house_farm.items():
            await house_repo.update_treasury(house_id, total)

        # O'lpon: vassal xonadoni Hukmdor xonadoniga 100 tanga/a'zo
        all_houses = await house_repo.get_all()
        for house in all_houses:
            if house.lord_id and house.high_lord_id:
                member_count = await user_repo.count_house_members(house.id)
                tribute = 100 * member_count
                await house_repo.update_treasury(house.id, -tribute)
                # Hukmdor xonadonini topib xazinasiga qo'shamiz
                hl_result = await session.execute(
                    select(User).where(User.id == house.high_lord_id)
                )
                hl_user = hl_result.scalar_one_or_none()
                if hl_user and hl_user.house_id:
                    await house_repo.update_treasury(hl_user.house_id, tribute)

        # Referal hisoblagichni nollash
        await session.execute(update(User).values(referral_count_today=0))
        await session.commit()

        logger.info("✅ Kunlik farm bajarildi")

        # Xabarnoma (faqat lord va high_lord ga)
        for user in all_users:
            if user.role == RoleEnum.ADMIN or not user.house_id:
                continue
            if scheduled_amount > 0:
                amount = scheduled_amount
            elif user.role not in [RoleEnum.LORD, RoleEnum.HIGH_LORD]:
                amount = 20
            else:
                amount = 50
            try:
                await bot.send_message(
                    user.id,
                    f"🌾 <b>Kunlik farm!</b>\n"
                    f"+{amount} tanga xonadon xazinasiga qo'shildi.",
                    parse_mode="HTML"
                )
            except Exception:
                pass


async def check_grace_period_job(bot: Bot):
    """Grace Period tugagan urushlarni FIGHTING ga o'tkazish"""
    from utils.chronicle import post_to_chronicle, format_chronicle
    async with AsyncSessionFactory() as session:
        war_repo = WarRepo(session)
        active_wars = await war_repo.get_all_active()
        now = datetime.utcnow()

        for war in active_wars:
            if war.status == WarStatusEnum.GRACE_PERIOD and war.grace_ends_at and war.grace_ends_at <= now:
                await war_repo.update_status(war.id, WarStatusEnum.FIGHTING)
                logger.info(f"Urush #{war.id} FIGHTING bosqichiga o'tdi")
                try:
                    await bot.send_message(
                        war.attacker.lord_id or 0,
                        f"⚔️ <b>JANG BOSHLANMOQDA!</b>\n{war.defender.name} bilan jang soat 23:00 ga qadar.",
                        parse_mode="HTML"
                    )
                    await bot.send_message(
                        war.defender.lord_id or 0,
                        f"⚔️ <b>JANG BOSHLANMOQDA!</b>\n{war.attacker.name} sizga hujum qilmoqda! Oldini ol!",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass


async def end_war_time_job(bot: Bot):
    """23:00 da barcha aktiv urushlarni avtomatik yakunlash"""
    from utils.battle import calculate_battle
    from utils.chronicle import post_to_chronicle, format_chronicle
    from config.settings import settings
    from sqlalchemy import update as sql_update

    async with AsyncSessionFactory() as session:
        war_repo = WarRepo(session)
        house_repo = HouseRepo(session)
        chronicle_repo = ChronicleRepo(session)

        active_wars = await war_repo.get_all_active()
        for war in active_wars:
            if war.status not in [WarStatusEnum.FIGHTING, WarStatusEnum.GRACE_PERIOD]:
                continue

            attacker = war.attacker
            defender = war.defender

            # Ittifoqchi yordamlarini yuklash
            from database.models import WarAllySupport
            from utils.battle import AllyContribution
            from sqlalchemy import select as sa_select
            from sqlalchemy.orm import selectinload as sa_selectinload
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

            # Hisob-kitob
            result = calculate_battle(
                attacker, defender,
                defender_gold=defender.treasury,
                attacker_allies=attacker_allies,
                defender_allies=defender_allies,
            )

            # G'olibga o'lja berish
            if result.attacker_wins:
                await house_repo.update_treasury(attacker.id, result.loot_gold)
                await house_repo.update_treasury(defender.id, -min(result.loot_gold, defender.treasury))
                await house_repo.update_military(
                    attacker.id,
                    soldiers=-result.attacker_soldiers_lost,
                    dragons=-result.attacker_dragons_lost,
                )
                await house_repo.update_military(
                    defender.id,
                    soldiers=-result.defender_soldiers_lost,
                    dragons=-result.defender_dragons_lost,
                )
                await _handle_lord_succession(session, war, bot)
            else:
                await house_repo.update_treasury(defender.id, result.loot_gold)
                await house_repo.update_treasury(attacker.id, -min(result.loot_gold, attacker.treasury))
                await house_repo.update_military(
                    attacker.id,
                    soldiers=-result.attacker_soldiers_lost,
                    dragons=-result.attacker_dragons_lost,
                )
                await house_repo.update_military(
                    defender.id,
                    soldiers=-result.defender_soldiers_lost,
                    dragons=-result.defender_dragons_lost,
                )

            # Ittifoqchi yo'qotmalarini qo'llash
            for house_id, losses in result.attacker_ally_losses.items():
                if losses["soldiers"] > 0 or losses["dragons"] > 0:
                    await house_repo.update_military(
                        house_id,
                        soldiers=-losses["soldiers"],
                        dragons=-losses["dragons"],
                        scorpions=-losses.get("scorpions", 0),
                    )
            for house_id, losses in result.defender_ally_losses.items():
                if losses["soldiers"] > 0 or losses["dragons"] > 0:
                    await house_repo.update_military(
                        house_id,
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

            # Xronika
            winner = attacker if result.winner_id == attacker.id else defender
            loser = defender if result.winner_id == attacker.id else attacker
            text = format_chronicle(
                "war_ended",
                winner=winner.name, loser=loser.name,
                loot=result.loot_gold,
                att_lost_s=result.attacker_soldiers_lost,
                att_lost_d=result.attacker_dragons_lost,
                def_lost_s=result.defender_soldiers_lost,
                def_lost_d=result.defender_dragons_lost,
            )
            tg_id = await post_to_chronicle(bot, text)
            await chronicle_repo.add("war_ended", text, house_id=winner.id, tg_msg_id=tg_id)

            # Lordlarga natijani yuborish
            for lord_id in [attacker.lord_id, defender.lord_id]:
                if lord_id:
                    try:
                        await bot.send_message(lord_id, text, parse_mode="HTML")
                    except Exception:
                        pass


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
    from database.repositories import IronBankRepo, UserRepo
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

        for loan in overdue:
            user = await user_repo.get_by_id(loan.user_id)
            if user and user.debt > 0:
                await iron_bank_repo.confiscate_for_debt(user)
                try:
                    await bot.send_message(
                        user.id,
                        "🏦 <b>TEMIR BANK MUSODARA!</b>\n\n"
                        "Qarzingiz muddati o'tdi. Barcha qo'shin va ajdarlaringiz musodara qilindi!",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

        logger.info(f"Temir Bank tekshiruvi: {len(overdue)} ta muddati o'tgan qarz topildi")


async def reload_farm_jobs(bot):
    """Admin farm jadvalini o'zgartirganda schedulerni qayta yuklash"""
    from main import scheduler as global_scheduler
    async with AsyncSessionFactory() as session:
        from database.repositories import BotSettingsRepo
        cfg = BotSettingsRepo(session)
        farm_schedules = await cfg.get_farm_schedules()

    # Eski farm joblarini o'chirish
    for job in global_scheduler.get_jobs():
        if job.id.startswith("daily_farm_"):
            global_scheduler.remove_job(job.id)

    # Yangilarini qo'shish
    for i, sched in enumerate(farm_schedules):
        global_scheduler.add_job(
            daily_farm_job,
            CronTrigger(hour=sched["hour"], minute=sched["minute"]),
            args=[bot, sched["amount"]],
            id=f"daily_farm_{i}",
            replace_existing=True,
        )
        logger.info(f"Farm job qayta yuklandi #{i}: {sched['hour']:02d}:{sched['minute']:02d} — {sched['amount']} tanga")


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

    # Yangi farm jadvallarini qo'shish
    for i, sched in enumerate(farm_schedules):
        scheduler.add_job(
            daily_farm_job,
            CronTrigger(hour=sched["hour"], minute=sched["minute"]),
            args=[bot, sched["amount"]],
            id=f"daily_farm_{i}",
            replace_existing=True,
        )
        logger.info(f"Farm job #{i}: {sched['hour']:02d}:{sched['minute']:02d} — {sched['amount']} tanga")

    if not farm_schedules:
        # Default agar jadval bo'sh bo'lsa
        scheduler.add_job(
            daily_farm_job,
            CronTrigger(hour=8, minute=0),
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

    # Urush tugashi - har kuni 23:00 UTC
    scheduler.add_job(
        end_war_time_job,
        CronTrigger(hour=23, minute=0),
        args=[bot],
        id="war_end",
        replace_existing=True,
    )

    # Temir Bank tekshiruvi - har kuni 00:00 UTC
    scheduler.add_job(
        check_iron_bank_debt_job,
        CronTrigger(hour=0, minute=0),
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
    """1 soat ichida javob bermagan xonadonlarni rad etilgan deb belgilash va urush boshlash"""
    from database.models import HukmdorClaim, HukmdorClaimResponse, ClaimStatusEnum, WarTypeEnum
    from database.repositories import HukmdorClaimRepo, HouseRepo, WarRepo
    from sqlalchemy import select
    from datetime import datetime, timedelta

    async with AsyncSessionFactory() as session:
        claim_repo = HukmdorClaimRepo(session)
        house_repo = HouseRepo(session)
        war_repo = WarRepo(session)

        # Faol PENDING da'volar
        result = await session.execute(
            select(HukmdorClaim).where(
                HukmdorClaim.status == ClaimStatusEnum.PENDING,
            )
        )
        claims = result.scalars().all()

        now = datetime.utcnow()
        local_hour = (now.hour + 5) % 24
        war_possible = settings.WAR_START_HOUR <= local_hour < settings.WAR_DECLARE_DEADLINE

        for claim in claims:
            # 1 soatdan oshgan da'vo
            if (now - claim.created_at).total_seconds() < 3600:
                continue

            responses = await claim_repo.get_all_responses(claim.id)
            claimant = await house_repo.get_by_id(claim.claimant_house_id)

            for resp in responses:
                if resp.accepted is not None:
                    continue

                # Javob bermagan — rad etilgan deb hisoblanadi
                await claim_repo.set_response(claim.id, resp.house_id, accepted=False)
                defender = await house_repo.get_by_id(resp.house_id)

                if defender and defender.lord_id:
                    try:
                        await bot.send_message(
                            defender.lord_id,
                            f"⏰ <b>Muddati o'tdi!</b>\n\n"
                            f"<b>{claimant.name}</b> xonadonining hukmdorlik da'vosiga "
                            f"javob bermaganligi sababli rad etildi.\n"
                            f"{'⚔️ Urush boshlanmoqda!' if war_possible else '⚔️ Urush vaqtida boshlanadi.'}",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass

                if war_possible:
                    active = await war_repo.get_active_war(resp.house_id)
                    if not active:
                        grace_ends = now + timedelta(minutes=settings.GRACE_PERIOD_MINUTES)
                        war = await war_repo.create_war(claimant.id, resp.house_id, grace_ends)
                        from sqlalchemy import update
                        from database.models import War
                        await session.execute(
                            update(War).where(War.id == war.id).values(
                                war_type=WarTypeEnum.CIVIL,
                                claim_id=claim.id,
                            )
                        )
                        await session.commit()

            await claim_repo.set_status(claim.id, ClaimStatusEnum.IN_PROGRESS)
