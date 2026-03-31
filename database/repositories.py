from datetime import datetime, date
from typing import Sequence

from sqlalchemy import select, update, delete, and_
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    User, House, War, WarAllySupport, Alliance,
    HukmdorClaim, HukmdorClaimResponse, IronBankLoan,
    MarketPrice, BotSettings, Chronicle, InternalMessage,
    FarmSchedule,
    UserRole, WarStatus, AllianceStatus, ClaimStatus, LoanStatus, Region
)


# ── UserRepo ──────────────────────────────────────────────────────────────────

class UserRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, user_id: int) -> User | None:
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_all_active(self) -> list[User]:
        result = await self.session.execute(
            select(User).where(User.is_active == True)
        )
        return list(result.scalars().all())

    async def get_house_members(self, house_id: int) -> list[User]:
        result = await self.session.execute(
            select(User).where(
                and_(User.house_id == house_id, User.is_active == True)
            )
        )
        return list(result.scalars().all())

    async def create(
        self,
        user_id: int,
        username: str | None,
        full_name: str,
    ) -> User:
        user = User(id=user_id, username=username, full_name=full_name)
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def update_role(self, user_id: int, role: UserRole) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(role=role)
        )
        await self.session.commit()

    async def set_house(self, user_id: int, house_id: int) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(house_id=house_id)
        )
        await self.session.commit()

    async def exile(self, user_id: int, exiled: bool = True) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(is_exiled=exiled)
        )
        await self.session.commit()

    async def update_last_farm_date(self, user_id: int, dt: datetime) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(last_farm_date=dt)
        )
        await self.session.commit()

    async def get_referral_count_today(self, user_id: int) -> int:
        result = await self.session.execute(
            select(User).where(
                and_(User.referral_by == user_id, User.is_active == True)
            )
        )
        users = result.scalars().all()
        today = date.today()
        return sum(
            1 for u in users
            if u.created_at and u.created_at.date() == today
        )

    async def reset_referral_counts(self) -> None:
        await self.session.execute(
            update(User).values(referral_count_today=0)
        )
        await self.session.commit()

    async def get_top_by_soldiers(self, limit: int = 10) -> list[User]:
        result = await self.session.execute(
            select(User)
            .where(User.is_active == True)
            .order_by(User.soldiers.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


# ── HouseRepo ─────────────────────────────────────────────────────────────────

class HouseRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, house_id: int) -> House | None:
        result = await self.session.execute(
            select(House).where(House.id == house_id)
        )
        return result.scalar_one_or_none()

    async def get_all_active(self) -> list[House]:
        result = await self.session.execute(
            select(House).where(House.is_active == True)
        )
        return list(result.scalars().all())

    async def get_by_region(self, region: Region) -> list[House]:
        result = await self.session.execute(
            select(House).where(
                and_(House.region == region, House.is_active == True)
            )
        )
        return list(result.scalars().all())

    async def create(self, name: str, region: Region) -> House:
        house = House(name=name, region=region)
        self.session.add(house)
        await self.session.commit()
        await self.session.refresh(house)
        return house

    async def update_treasury(self, house_id: int, delta: int) -> None:
        """Xazinaga delta qo'shadi (manfiy bo'lsa kamaytiradi)."""
        result = await self.session.execute(
            select(House).where(House.id == house_id)
        )
        house = result.scalar_one_or_none()
        if house:
            house.treasury = max(0, house.treasury + delta)
            await self.session.commit()

    async def set_lord(self, house_id: int, lord_id: int | None) -> None:
        await self.session.execute(
            update(House).where(House.id == house_id).values(lord_id=lord_id)
        )
        await self.session.commit()

    async def set_high_lord(self, house_id: int, high_lord_id: int | None) -> None:
        await self.session.execute(
            update(House).where(House.id == house_id).values(high_lord_id=high_lord_id)
        )
        await self.session.commit()

    async def update_troops(
        self,
        house_id: int,
        soldiers: int = 0,
        dragons: int = 0,
        scorpions: int = 0,
    ) -> None:
        result = await self.session.execute(
            select(House).where(House.id == house_id)
        )
        house = result.scalar_one_or_none()
        if house:
            house.total_soldiers = max(0, house.total_soldiers + soldiers)
            house.total_dragons = max(0, house.total_dragons + dragons)
            house.total_scorpions = max(0, house.total_scorpions + scorpions)
            await self.session.commit()

    async def set_occupation(
        self,
        house_id: int,
        occupied: bool,
        occupier_id: int | None = None,
        tax_rate: float = 0.0,
    ) -> None:
        await self.session.execute(
            update(House).where(House.id == house_id).values(
                is_under_occupation=occupied,
                occupier_house_id=occupier_id,
                permanent_tax_rate=tax_rate,
            )
        )
        await self.session.commit()

    async def get_top_by_treasury(self, limit: int = 10) -> list[House]:
        result = await self.session.execute(
            select(House)
            .where(House.is_active == True)
            .order_by(House.treasury.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


# ── WarRepo ───────────────────────────────────────────────────────────────────

class WarRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, war_id: int) -> War | None:
        result = await self.session.execute(
            select(War).where(War.id == war_id)
        )
        return result.scalar_one_or_none()

    async def get_active_wars(self) -> list[War]:
        result = await self.session.execute(
            select(War).where(War.status != WarStatus.ended)
        )
        return list(result.scalars().all())

    async def get_grace_period_wars(self) -> list[War]:
        result = await self.session.execute(
            select(War).where(War.status == WarStatus.grace_period)
        )
        return list(result.scalars().all())

    async def get_fighting_wars(self) -> list[War]:
        result = await self.session.execute(
            select(War).where(War.status == WarStatus.fighting)
        )
        return list(result.scalars().all())

    async def create(
        self,
        attacker_house_id: int,
        defender_house_id: int,
        is_civil_war: bool = False,
    ) -> War:
        war = War(
            attacker_house_id=attacker_house_id,
            defender_house_id=defender_house_id,
            is_civil_war=is_civil_war,
        )
        self.session.add(war)
        await self.session.commit()
        await self.session.refresh(war)
        return war

    async def update_status(self, war_id: int, status: WarStatus) -> None:
        await self.session.execute(
            update(War).where(War.id == war_id).values(status=status)
        )
        await self.session.commit()

    async def end_war(
        self,
        war_id: int,
        winner_house_id: int | None,
        attacker_losses: dict,
        defender_losses: dict,
        gold_looted: int,
    ) -> None:
        await self.session.execute(
            update(War).where(War.id == war_id).values(
                status=WarStatus.ended,
                winner_house_id=winner_house_id,
                gold_looted=gold_looted,
                ended_at=datetime.utcnow(),
                **attacker_losses,
                **defender_losses,
            )
        )
        await self.session.commit()

    async def get_house_wars(self, house_id: int) -> list[War]:
        result = await self.session.execute(
            select(War).where(
                (War.attacker_house_id == house_id) |
                (War.defender_house_id == house_id)
            ).order_by(War.declared_at.desc())
        )
        return list(result.scalars().all())

    async def get_civil_wars_by_region(self, region: Region) -> list[War]:
        result = await self.session.execute(
            select(War).where(
                and_(War.is_civil_war == True, War.status != WarStatus.ended)
            )
        )
        return list(result.scalars().all())


# ── AllianceRepo ──────────────────────────────────────────────────────────────

class AllianceRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_active_alliance(
        self, house1_id: int, house2_id: int
    ) -> Alliance | None:
        result = await self.session.execute(
            select(Alliance).where(
                and_(
                    Alliance.status == AllianceStatus.active,
                    (
                        (Alliance.house1_id == house1_id) & (Alliance.house2_id == house2_id)
                    ) | (
                        (Alliance.house1_id == house2_id) & (Alliance.house2_id == house1_id)
                    )
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_house_alliances(self, house_id: int) -> list[Alliance]:
        result = await self.session.execute(
            select(Alliance).where(
                and_(
                    Alliance.status == AllianceStatus.active,
                    (Alliance.house1_id == house_id) | (Alliance.house2_id == house_id)
                )
            )
        )
        return list(result.scalars().all())

    async def create(self, house1_id: int, house2_id: int) -> Alliance:
        alliance = Alliance(house1_id=house1_id, house2_id=house2_id)
        self.session.add(alliance)
        await self.session.commit()
        await self.session.refresh(alliance)
        return alliance

    async def dissolve(self, alliance_id: int) -> None:
        await self.session.execute(
            update(Alliance).where(Alliance.id == alliance_id).values(
                status=AllianceStatus.dissolved,
                dissolved_at=datetime.utcnow(),
            )
        )
        await self.session.commit()

    async def dissolve_all_for_house(self, house_id: int) -> None:
        await self.session.execute(
            update(Alliance).where(
                and_(
                    Alliance.status == AllianceStatus.active,
                    (Alliance.house1_id == house_id) | (Alliance.house2_id == house_id)
                )
            ).values(
                status=AllianceStatus.dissolved,
                dissolved_at=datetime.utcnow(),
            )
        )
        await self.session.commit()


# ── IronBankRepo ──────────────────────────────────────────────────────────────

class IronBankRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_active_loan(self, house_id: int) -> IronBankLoan | None:
        result = await self.session.execute(
            select(IronBankLoan).where(
                and_(
                    IronBankLoan.house_id == house_id,
                    IronBankLoan.status == LoanStatus.active,
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_overdue_loans(self) -> list[IronBankLoan]:
        now = datetime.utcnow()
        result = await self.session.execute(
            select(IronBankLoan).where(
                and_(
                    IronBankLoan.status == LoanStatus.active,
                    IronBankLoan.due_date < now,
                )
            )
        )
        return list(result.scalars().all())

    async def create(
        self,
        house_id: int,
        amount: int,
        interest_rate: float,
        total_due: int,
        due_date: datetime,
    ) -> IronBankLoan:
        loan = IronBankLoan(
            house_id=house_id,
            amount=amount,
            interest_rate=interest_rate,
            total_due=total_due,
            due_date=due_date,
        )
        self.session.add(loan)
        await self.session.commit()
        await self.session.refresh(loan)
        return loan

    async def pay(self, loan_id: int) -> None:
        await self.session.execute(
            update(IronBankLoan).where(IronBankLoan.id == loan_id).values(
                status=LoanStatus.paid,
                paid_at=datetime.utcnow(),
            )
        )
        await self.session.commit()

    async def mark_defaulted(self, loan_id: int) -> None:
        await self.session.execute(
            update(IronBankLoan).where(IronBankLoan.id == loan_id).values(
                status=LoanStatus.defaulted
            )
        )
        await self.session.commit()


# ── MarketRepo ────────────────────────────────────────────────────────────────

class MarketRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_price(self, item_type: str) -> int | None:
        result = await self.session.execute(
            select(MarketPrice).where(MarketPrice.item_type == item_type)
        )
        mp = result.scalar_one_or_none()
        return mp.price if mp else None

    async def get_all(self) -> list[MarketPrice]:
        result = await self.session.execute(select(MarketPrice))
        return list(result.scalars().all())

    async def set_price(self, item_type: str, price: int) -> None:
        result = await self.session.execute(
            select(MarketPrice).where(MarketPrice.item_type == item_type)
        )
        mp = result.scalar_one_or_none()
        if mp:
            mp.price = price
        else:
            mp = MarketPrice(item_type=item_type, price=price)
            self.session.add(mp)
        await self.session.commit()


# ── BotSettingsRepo ───────────────────────────────────────────────────────────

class BotSettingsRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, key: str) -> str | None:
        result = await self.session.execute(
            select(BotSettings).where(BotSettings.key == key)
        )
        setting = result.scalar_one_or_none()
        return setting.value if setting else None

    async def set(self, key: str, value: str) -> None:
        result = await self.session.execute(
            select(BotSettings).where(BotSettings.key == key)
        )
        setting = result.scalar_one_or_none()
        if setting:
            setting.value = value
        else:
            setting = BotSettings(key=key, value=value)
            self.session.add(setting)
        await self.session.commit()


# ── ChronicleRepo ─────────────────────────────────────────────────────────────

class ChronicleRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(
        self,
        event_type: str,
        content: str,
        telegram_message_id: int | None = None,
    ) -> Chronicle:
        chronicle = Chronicle(
            event_type=event_type,
            content=content,
            telegram_message_id=telegram_message_id,
        )
        self.session.add(chronicle)
        await self.session.commit()
        await self.session.refresh(chronicle)
        return chronicle

    async def get_recent(self, limit: int = 20) -> list[Chronicle]:
        result = await self.session.execute(
            select(Chronicle).order_by(Chronicle.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())


# ── HukmdorClaimRepo ──────────────────────────────────────────────────────────

class HukmdorClaimRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_active_by_region(self, region: Region) -> HukmdorClaim | None:
        result = await self.session.execute(
            select(HukmdorClaim).where(
                and_(
                    HukmdorClaim.region == region,
                    HukmdorClaim.status == ClaimStatus.pending,
                )
            )
        )
        return result.scalar_one_or_none()

    async def create(self, claimant_house_id: int, region: Region) -> HukmdorClaim:
        claim = HukmdorClaim(claimant_house_id=claimant_house_id, region=region)
        self.session.add(claim)
        await self.session.commit()
        await self.session.refresh(claim)
        return claim

    async def update_status(self, claim_id: int, status: ClaimStatus) -> None:
        await self.session.execute(
            update(HukmdorClaim).where(HukmdorClaim.id == claim_id).values(
                status=status,
                resolved_at=datetime.utcnow(),
            )
        )
        await self.session.commit()

    async def get_pending_claims(self) -> list[HukmdorClaim]:
        result = await self.session.execute(
            select(HukmdorClaim).where(HukmdorClaim.status == ClaimStatus.pending)
        )
        return list(result.scalars().all())


# ── YANGI: FarmScheduleRepo ───────────────────────────────────────────────────

class FarmScheduleRepo:
    """
    Admin tomonidan belgilangan kunlik farm vaqtlari va miqdorlarini boshqaradi.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_all_active(self) -> list[FarmSchedule]:
        """Faqat faol (is_active=True) farmlarni vaqt tartibida qaytaradi."""
        result = await self.session.execute(
            select(FarmSchedule)
            .where(FarmSchedule.is_active == True)
            .order_by(FarmSchedule.hour, FarmSchedule.minute)
        )
        return list(result.scalars().all())

    async def get_all(self) -> list[FarmSchedule]:
        """Barcha farmlarni (faol va nofaol) vaqt tartibida qaytaradi."""
        result = await self.session.execute(
            select(FarmSchedule)
            .order_by(FarmSchedule.hour, FarmSchedule.minute)
        )
        return list(result.scalars().all())

    async def get_by_id(self, schedule_id: int) -> FarmSchedule | None:
        result = await self.session.execute(
            select(FarmSchedule).where(FarmSchedule.id == schedule_id)
        )
        return result.scalar_one_or_none()

    async def exists(self, hour: int, minute: int) -> bool:
        """Berilgan vaqtda farm allaqachon borligini tekshiradi."""
        result = await self.session.execute(
            select(FarmSchedule).where(
                and_(FarmSchedule.hour == hour, FarmSchedule.minute == minute)
            )
        )
        return result.scalar_one_or_none() is not None

    async def add(self, hour: int, minute: int, amount: int) -> FarmSchedule:
        """Yangi farm jadvali qo'shadi."""
        schedule = FarmSchedule(hour=hour, minute=minute, amount=amount)
        self.session.add(schedule)
        await self.session.commit()
        await self.session.refresh(schedule)
        return schedule

    async def update_amount(self, schedule_id: int, amount: int) -> FarmSchedule | None:
        """Farm miqdorini yangilaydi."""
        result = await self.session.execute(
            select(FarmSchedule).where(FarmSchedule.id == schedule_id)
        )
        schedule = result.scalar_one_or_none()
        if not schedule:
            return None
        schedule.amount = amount
        await self.session.commit()
        await self.session.refresh(schedule)
        return schedule

    async def toggle_active(self, schedule_id: int) -> FarmSchedule | None:
        """Farm'ni faol/nofaol holatga o'tkazadi."""
        result = await self.session.execute(
            select(FarmSchedule).where(FarmSchedule.id == schedule_id)
        )
        schedule = result.scalar_one_or_none()
        if not schedule:
            return None
        schedule.is_active = not schedule.is_active
        await self.session.commit()
        await self.session.refresh(schedule)
        return schedule

    async def delete(self, schedule_id: int) -> bool:
        """Farm'ni o'chiradi. Muvaffaqiyatli bo'lsa True qaytaradi."""
        result = await self.session.execute(
            select(FarmSchedule).where(FarmSchedule.id == schedule_id)
        )
        schedule = result.scalar_one_or_none()
        if not schedule:
            return False
        await self.session.delete(schedule)
        await self.session.commit()
        return True

    async def clear_all(self) -> int:
        """Barcha farm jadvallarini o'chiradi. O'chirilgan sonini qaytaradi."""
        result = await self.session.execute(select(FarmSchedule))
        count = len(result.scalars().all())
        await self.session.execute(delete(FarmSchedule))
        await self.session.commit()
        return count
