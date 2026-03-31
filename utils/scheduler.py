import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from database.engine import async_session_maker
from database.repositories import (
    HouseRepo, UserRepo, WarRepo, IronBankRepo,
    HukmdorClaimRepo, FarmScheduleRepo
)
from database.models import WarStatus, ClaimStatus

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# FARM JOBS
# ═══════════════════════════════════════════════════════════════════════════════

async def run_farm_job(amount: int):
    """
    Belgilangan miqdorda farm.
    Barcha faol xonadondagi a'zolar soniga ko'ra xazinaga tanga qo'shadi.
    Hisob: amount × a'zolar_soni → xonadon xazinasiga.
    """
    logger.info(f"[FARM] Ishga tushdi — har a'zo uchun {amount} tanga.")
    async with async_session_maker() as session:
        house_repo = HouseRepo(session)
        user_repo = UserRepo(session)

        houses = await house_repo.get_all_active()
        total_houses = 0
        total_gold = 0

        for house in houses:
            members = await user_repo.get_house_members(house.id)
            if not members:
                continue

            earned = amount * len(members)
            await house_repo.update_treasury(house.id, earned)
            total_houses += 1
            total_gold += earned
            logger.info(
                f"  → Xonadon #{house.id} ({house.name}): "
                f"+{earned} tanga ({len(members)} a'zo × {amount})"
            )

        logger.info(
            f"[FARM] Yakunlandi — {total_houses} xonadon, "
            f"jami {total_gold} tanga tarqatildi."
        )


async def reload_farm_schedules(scheduler: AsyncIOScheduler):
    """
    DB dagi farm_schedules jadvalini o'qib, APScheduler'ga dinamik job'lar qo'shadi.

    Avvalgi barcha 'farm_*' job'larini tozalab, DB dagi faol jadvallar asosida
    yangi job'lar ro'yxatdan o'tkazadi. Admin farm qo'shganda yoki o'chirganda
    bu funksiya chaqiriladi.
    """
    # 1. Avvalgi farm job'larini o'chirish
    removed = 0
    for job in scheduler.get_jobs():
        if job.id.startswith("farm_"):
            scheduler.remove_job(job.id)
            removed += 1
    if removed:
        logger.info(f"[FARM RELOAD] {removed} ta eski farm job o'chirildi.")

    # 2. DB dan faol jadvallarni o'qish
    async with async_session_maker() as session:
        repo = FarmScheduleRepo(session)
        schedules = await repo.get_all_active()

    if not schedules:
        logger.warning("[FARM RELOAD] Faol farm jadvali yo'q — hech qanday job qo'shilmadi.")
        return

    # 3. Har bir jadval uchun yangi job qo'shish
    for s in schedules:
        job_id = f"farm_{s.id}_{s.hour:02d}{s.minute:02d}"
        scheduler.add_job(
            run_farm_job,
            trigger=CronTrigger(
                hour=s.hour,
                minute=s.minute,
                timezone="Asia/Tashkent"
            ),
            args=[s.amount],
            id=job_id,
            replace_existing=True,
            name=f"🌾 Farm {s.time_str()} — {s.amount} tanga",
        )
        logger.info(
            f"[FARM RELOAD] Job qo'shildi: {s.time_str()} → {s.amount} tanga (id={job_id})"
        )

    logger.info(f"[FARM RELOAD] Jami {len(schedules)} ta farm job faollashtirildi.")


# ═══════════════════════════════════════════════════════════════════════════════
# O'LPON (TRIBUTE) JOB
# ═══════════════════════════════════════════════════════════════════════════════

async def daily_tribute_job():
    """
    Vassal xonadonlardan hukmdor xonadoniga kunlik o'lpon undiradi.
    O'lpon: 100 tanga × vassal xonadon a'zolari soni.
    """
    logger.info("[TRIBUTE] O'lpon undirish boshlandi.")
    async with async_session_maker() as session:
        house_repo = HouseRepo(session)
        user_repo = UserRepo(session)

        houses = await house_repo.get_all_active()
        for house in houses:
            if not house.is_under_occupation or not house.occupier_house_id:
                continue

            members = await user_repo.get_house_members(house.id)
            tribute = 100 * len(members)
            if tribute <= 0:
                continue

            # Vassal xazinasidan undirish
            await house_repo.update_treasury(house.id, -tribute)
            # Hukmdor xazinasiga qo'shish
            await house_repo.update_treasury(house.occupier_house_id, tribute)
            logger.info(
                f"  → Vassal #{house.id} → Hukmdor #{house.occupier_house_id}: "
                f"{tribute} tanga o'lpon"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# URUSH JOBS
# ═══════════════════════════════════════════════════════════════════════════════

async def check_grace_period_job():
    """Grace period tugagan urushlarni FIGHTING holatiga o'tkazadi."""
    from datetime import timedelta
    async with async_session_maker() as session:
        war_repo = WarRepo(session)
        grace_wars = await war_repo.get_grace_period_wars()

        for war in grace_wars:
            grace_end = war.declared_at + timedelta(minutes=60)
            if datetime.utcnow() >= grace_end:
                await war_repo.update_status(war.id, WarStatus.fighting)
                logger.info(f"[WAR] #{war.id} Grace Period → Fighting")


async def end_war_time_job():
    """
    23:00 da barcha faol urushlarni avtomatik yakunlaydi.
    Jang natijasini utils.battle moduli orqali hisoblaydi.
    """
    from utils.battle import calculate_battle_result

    logger.info("[WAR] 23:00 — Barcha urushlar yakunlanmoqda.")
    async with async_session_maker() as session:
        war_repo = WarRepo(session)
        house_repo = HouseRepo(session)

        active_wars = await war_repo.get_active_wars()
        for war in active_wars:
            if war.status == WarStatus.ended:
                continue

            attacker = await house_repo.get_by_id(war.attacker_house_id)
            defender = await house_repo.get_by_id(war.defender_house_id)
            if not attacker or not defender:
                continue

            result = await calculate_battle_result(attacker, defender)
            await war_repo.end_war(
                war_id=war.id,
                winner_house_id=result["winner_id"],
                attacker_losses=result["attacker_losses"],
                defender_losses=result["defender_losses"],
                gold_looted=result["gold_looted"],
            )

            if result["winner_id"] == attacker.id:
                # G'olib oltin va qo'shinlar oladi
                await house_repo.update_treasury(attacker.id, result["gold_looted"])
                await house_repo.update_treasury(defender.id, -result["gold_looted"])
            logger.info(
                f"[WAR] #{war.id} yakunlandi. G'olib: {result['winner_id']}"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# BANK JOBS
# ═══════════════════════════════════════════════════════════════════════════════

async def check_iron_bank_debt_job():
    """
    Muddati o'tgan qarzlar uchun xonadon qo'shinlari va ajdarlarini musodara qiladi.
    """
    logger.info("[BANK] Muddati o'tgan qarzlar tekshirilmoqda.")
    async with async_session_maker() as session:
        bank_repo = IronBankRepo(session)
        house_repo = HouseRepo(session)

        overdue_loans = await bank_repo.get_overdue_loans()
        for loan in overdue_loans:
            house = await house_repo.get_by_id(loan.house_id)
            if not house:
                continue

            # Qo'shinlarning 50% musodara qilinadi
            soldiers_seized = house.total_soldiers // 2
            dragons_seized = house.total_dragons // 2
            scorpions_seized = house.total_scorpions // 2

            await house_repo.update_troops(
                loan.house_id,
                soldiers=-soldiers_seized,
                dragons=-dragons_seized,
                scorpions=-scorpions_seized,
            )
            await bank_repo.mark_defaulted(loan.id)
            logger.info(
                f"[BANK] Xonadon #{loan.house_id} default — "
                f"{soldiers_seized} askar, {dragons_seized} ajdar, "
                f"{scorpions_seized} skorpion musodara qilindi."
            )


# ═══════════════════════════════════════════════════════════════════════════════
# CIVIL WAR / CLAIM JOBS
# ═══════════════════════════════════════════════════════════════════════════════

async def check_civil_wars_job():
    """
    Civil urushlar tugashini tekshiradi va g'olib hukmdorni belgilaydi.
    """
    async with async_session_maker() as session:
        war_repo = WarRepo(session)
        house_repo = HouseRepo(session)
        claim_repo = HukmdorClaimRepo(session)

        civil_wars = await war_repo.get_civil_wars_by_region(None)  # region filter claim dan
        for war in civil_wars:
            if war.status != WarStatus.ended:
                continue
            if not war.winner_house_id:
                continue

            winner = await house_repo.get_by_id(war.winner_house_id)
            if not winner:
                continue

            # G'olib High Lord bo'ladi
            if winner.lord_id:
                await house_repo.set_high_lord(winner.id, winner.lord_id)
                logger.info(
                    f"[CIVIL WAR] #{war.id} yakunlandi. "
                    f"Xonadon #{winner.id} hukmdor bo'ldi."
                )


async def check_claim_timeouts_job():
    """
    1 soat ichida javob bermagan da'volarni rad etilgan deb belgilaydi.
    """
    from datetime import timedelta
    async with async_session_maker() as session:
        claim_repo = HukmdorClaimRepo(session)
        pending_claims = await claim_repo.get_pending_claims()

        for claim in pending_claims:
            timeout = claim.created_at + timedelta(hours=1)
            if datetime.utcnow() >= timeout.replace(tzinfo=None):
                await claim_repo.update_status(claim.id, ClaimStatus.rejected)
                logger.info(f"[CLAIM] #{claim.id} timeout — rad etildi.")


async def reset_referral_counts_job():
    """Har kuni yarim tunda referral_count_today ni nollaydi."""
    async with async_session_maker() as session:
        user_repo = UserRepo(session)
        await user_repo.reset_referral_counts()
        logger.info("[REFERRAL] Kunlik referral hisoblagichlari nollandi.")


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEDULER SETUP
# ═══════════════════════════════════════════════════════════════════════════════

def setup_static_jobs(scheduler: AsyncIOScheduler):
    """
    O'zgarmaydigan (statik) vazifalarni scheduler'ga qo'shadi.
    Farm job'lari bu yerda QO'SHILMAYDI — ular reload_farm_schedules() orqali
    DB dan dinamik yuklanadi.
    """

    # O'lpon: har kuni 08:05 da (farm dan keyin)
    scheduler.add_job(
        daily_tribute_job,
        trigger=CronTrigger(hour=8, minute=5, timezone="Asia/Tashkent"),
        id="daily_tribute",
        replace_existing=True,
        name="💰 Kunlik o'lpon",
    )

    # Urush tugashi: 23:00
    scheduler.add_job(
        end_war_time_job,
        trigger=CronTrigger(hour=23, minute=0, timezone="Asia/Tashkent"),
        id="end_war_time",
        replace_existing=True,
        name="⚔️ Urush tugashi",
    )

    # Bank qarz tekshiruvi: 00:00
    scheduler.add_job(
        check_iron_bank_debt_job,
        trigger=CronTrigger(hour=0, minute=0, timezone="Asia/Tashkent"),
        id="bank_debt_check",
        replace_existing=True,
        name="🏦 Bank qarz tekshiruvi",
    )

    # Grace period tekshiruvi: har 5 daqiqa
    scheduler.add_job(
        check_grace_period_job,
        trigger=CronTrigger(minute="*/5", timezone="Asia/Tashkent"),
        id="grace_period_check",
        replace_existing=True,
        name="🕐 Grace period tekshiruvi",
    )

    # Civil urush tekshiruvi: har 10 daqiqa
    scheduler.add_job(
        check_civil_wars_job,
        trigger=CronTrigger(minute="*/10", timezone="Asia/Tashkent"),
        id="civil_war_check",
        replace_existing=True,
        name="👑 Civil urush tekshiruvi",
    )

    # Da'vo timeout: har 15 daqiqa
    scheduler.add_job(
        check_claim_timeouts_job,
        trigger=CronTrigger(minute="*/15", timezone="Asia/Tashkent"),
        id="claim_timeout_check",
        replace_existing=True,
        name="📜 Da'vo timeout tekshiruvi",
    )

    # Referral nollash: har kuni 00:01
    scheduler.add_job(
        reset_referral_counts_job,
        trigger=CronTrigger(hour=0, minute=1, timezone="Asia/Tashkent"),
        id="reset_referrals",
        replace_existing=True,
        name="🔄 Referral hisoblagich nollash",
    )

    logger.info("[SCHEDULER] Statik job'lar qo'shildi.")
