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


async def daily_farm_job(bot: Bot):
    """Kunlik farm: Lord +50, A'zo +20 xazinaga"""
    async with AsyncSessionFactory() as session:
        user_repo = UserRepo(session)
        house_repo = HouseRepo(session)

        # Barcha foydalanuvchilarni olish
        result = await session.execute(select(User).where(User.is_active == True))
        all_users = result.scalars().all()

        for user in all_users:
            if user.role == RoleEnum.ADMIN:
                continue
            amount = 50 if user.role in [RoleEnum.HIGH_LORD, RoleEnum.LORD] else 20
            await user_repo.update_gold(user.id, amount)

        # O'lpon: Har vassal xonadoni Hukmdorga 100 tanga
        all_houses = await house_repo.get_all()
        for house in all_houses:
            if house.lord_id and house.high_lord_id:
                member_count = await user_repo.count_house_members(house.id)
                tribute = 100 * member_count
                await house_repo.update_treasury(house.id, -tribute)
                if house.high_lord_id:
                    await user_repo.update_gold(house.high_lord_id, tribute)

        # Referal bonuslari qayta hisoblash
        await session.execute(
            update(User).values(referral_count_today=0)
        )
        await session.commit()

        logger.info("✅ Kunlik farm bajarildi")

        # Xabarnoma
        for user in all_users:
            if user.role == RoleEnum.ADMIN:
                continue
            try:
                amount = 50 if user.role in [RoleEnum.HIGH_LORD, RoleEnum.LORD] else 20
                await bot.send_message(
                    user.id,
                    f"🌾 <b>Kunlik farm!</b>\n+{amount} oltin hisob-kitobingizga qo'shildi.",
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

            # Hisob-kitob
            result = calculate_battle(
                attacker, defender,
                attacker_gold=0,  # Uy xazinasidan keyin to'ldiriladi
                defender_gold=defender.treasury,
            )

            # G'olibga o'lja berish
            if result.winner_id == attacker.id:
                await house_repo.update_treasury(attacker.id, result.loot_gold)
                await house_repo.update_treasury(defender.id, -result.loot_gold)
                # Harbiy ko'rsatkich yangilash
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
                # Lord almashtirish
                await _handle_lord_succession(session, war, bot)
            else:
                await house_repo.update_treasury(defender.id, result.loot_gold)
                await house_repo.update_treasury(attacker.id, -result.loot_gold)

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


async def setup_scheduler(scheduler: AsyncIOScheduler, bot: Bot):
    # Kunlik farm - har kuni 08:00 UTC
    scheduler.add_job(
        daily_farm_job,
        CronTrigger(hour=8, minute=0),
        args=[bot],
        id="daily_farm",
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
