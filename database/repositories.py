from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func, and_, or_
from sqlalchemy.orm import selectinload
from database.models import (
    User, House, Alliance, War, IronBankLoan,
    InternalMessage, Chronicle, MarketPrice,
    RoleEnum, RegionEnum, WarStatusEnum,
    AllianceGroup, AllianceGroupMember, AllianceGroupInvite,
)
from typing import Optional, List
import math


class UserRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, user_id: int) -> Optional[User]:
        result = await self.session.execute(
            select(User).where(User.id == user_id).options(selectinload(User.house))
        )
        return result.scalar_one_or_none()

    async def create(self, user_id: int, full_name: str, username: str = None) -> User:
        user = User(id=user_id, full_name=full_name, username=username)
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def get_house_members(self, house_id: int) -> List[User]:
        result = await self.session.execute(
            select(User).where(User.house_id == house_id, User.is_active == True)
        )
        return result.scalars().all()

    async def count_house_members(self, house_id: int) -> int:
        result = await self.session.execute(
            select(func.count(User.id)).where(
                User.house_id == house_id, User.is_active == True
            )
        )
        return result.scalar_one()

    async def find_available_house(self) -> Optional[House]:
        """Bo'sh Lord o'rni yoki kamroq a'zoli xonadoni topish"""
        # Avval bo'sh Lord o'rni (lord_id = None bo'lgan)
        result = await self.session.execute(
            select(House).where(House.lord_id == None)
        )
        empty_lord_house = result.scalars().first()
        if empty_lord_house:
            return empty_lord_house, "lord"

        # Eng kam a'zoli xonadon
        subq = (
            select(User.house_id, func.count(User.id).label("cnt"))
            .where(User.is_active == True)
            .group_by(User.house_id)
            .subquery()
        )
        result = await self.session.execute(
            select(House)
            .outerjoin(subq, House.id == subq.c.house_id)
            .where(func.coalesce(subq.c.cnt, 0) < 10)
            .order_by(func.coalesce(subq.c.cnt, 0))
        )
        house = result.scalars().first()
        return house, "member"

    async def assign_to_house(self, user: User, house: House, role: RoleEnum):
        user.house_id = house.id
        user.region = house.region
        user.role = role
        if role == RoleEnum.LORD:
            house.lord_id = user.id
        await self.session.commit()

    async def get_most_active_member(self, house_id: int, exclude_id: int) -> Optional[User]:
        """Eng birinchi topilgan a'zo (keyingi lord uchun)"""
        result = await self.session.execute(
            select(User).where(
                User.house_id == house_id,
                User.role == RoleEnum.MEMBER,
                User.id != exclude_id,
                User.is_active == True
            ).order_by(User.id)
        )
        return result.scalars().first()

    async def exile_user(self, user: User, new_house_id: int):
        user.is_exiled = True
        user.house_id = new_house_id
        user.role = RoleEnum.MEMBER
        await self.session.commit()

    async def get_referral_count_today(self, user_id: int) -> int:
        result = await self.session.execute(
            select(func.count(User.id)).where(
                User.referral_by == user_id,
                func.date(User.created_at) == func.current_date()
            )
        )
        return result.scalar_one() or 0


class HouseRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, house_id: int) -> Optional[House]:
        result = await self.session.execute(
            select(House).where(House.id == house_id)
            .options(selectinload(House.members))
        )
        return result.scalar_one_or_none()

    async def get_by_region(self, region: RegionEnum) -> Optional[House]:
        result = await self.session.execute(
            select(House).where(House.region == region)
        )
        return result.scalar_one_or_none()

    async def get_all(self) -> List[House]:
        result = await self.session.execute(select(House))
        return result.scalars().all()

    async def get_all_by_region(self, region) -> List[House]:
        result = await self.session.execute(
            select(House).where(House.region == region)
        )
        return result.scalars().all()

    async def update_treasury(self, house_id: int, amount: int):
        await self.session.execute(
            update(House).where(House.id == house_id)
            .values(treasury=House.treasury + amount)
        )
        await self.session.commit()

    async def update_military(self, house_id: int, soldiers: int = 0, dragons: int = 0, scorpions: int = 0):
        await self.session.execute(
            update(House).where(House.id == house_id).values(
                total_soldiers=func.greatest(House.total_soldiers + soldiers, 0),
                total_dragons=func.greatest(House.total_dragons + dragons, 0),
                total_scorpions=func.greatest(House.total_scorpions + scorpions, 0),
            )
        )
        await self.session.commit()

    async def set_occupation(self, house_id: int, occupier_id: int, tax_rate: float):
        from datetime import datetime
        await self.session.execute(
            update(House).where(House.id == house_id).values(
                is_under_occupation=True,
                occupier_house_id=occupier_id,
                permanent_tax_rate=tax_rate,
                vassal_since=datetime.utcnow(),
            )
        )
        await self.session.commit()

    async def clear_occupation(self, house_id: int):
        """Xonadonni vassallikdan ozod qilish"""
        await self.session.execute(
            update(House).where(House.id == house_id).values(
                is_under_occupation=False,
                occupier_house_id=None,
                permanent_tax_rate=0.0,
                vassal_since=None,
            )
        )
        await self.session.commit()


class WarRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_war(self, attacker_id: int, defender_id: int, grace_ends_at) -> War:
        war = War(
            attacker_house_id=attacker_id,
            defender_house_id=defender_id,
            grace_ends_at=grace_ends_at,
            status=WarStatusEnum.GRACE_PERIOD,
        )
        self.session.add(war)
        await self.session.commit()
        await self.session.refresh(war)
        return war

    async def get_active_war(self, house_id: int) -> Optional[War]:
        result = await self.session.execute(
            select(War).where(
                or_(War.attacker_house_id == house_id, War.defender_house_id == house_id),
                War.status.in_([WarStatusEnum.DECLARED, WarStatusEnum.GRACE_PERIOD, WarStatusEnum.FIGHTING])
            ).options(selectinload(War.attacker), selectinload(War.defender))
        )
        return result.scalars().first()

    async def update_status(self, war_id: int, status: WarStatusEnum):
        await self.session.execute(
            update(War).where(War.id == war_id).values(status=status)
        )
        await self.session.commit()

    async def end_war(self, war_id: int, winner_id: int, loot: int, surrendered: bool = False, **kwargs):
        from datetime import datetime
        await self.session.execute(
            update(War).where(War.id == war_id).values(
                status=WarStatusEnum.ENDED,
                winner_house_id=winner_id,
                loot_gold=loot,
                defender_surrendered=surrendered,
                ended_at=datetime.utcnow(),
                **kwargs
            )
        )
        await self.session.commit()

    async def get_all_active(self) -> List[War]:
        from database.models import WarAllySupport
        result = await self.session.execute(
            select(War).where(
                War.status.in_([WarStatusEnum.GRACE_PERIOD, WarStatusEnum.FIGHTING])
            ).options(
                selectinload(War.attacker),
                selectinload(War.defender),
                selectinload(War.winner),
            )
        )
        return result.scalars().all()


class AllianceRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, house1_id: int, house2_id: int) -> Alliance:
        alliance = Alliance(house1_id=house1_id, house2_id=house2_id)
        self.session.add(alliance)
        await self.session.commit()
        return alliance

    async def get_active(self, house1_id: int, house2_id: int) -> Optional[Alliance]:
        result = await self.session.execute(
            select(Alliance).where(
                or_(
                    and_(Alliance.house1_id == house1_id, Alliance.house2_id == house2_id),
                    and_(Alliance.house1_id == house2_id, Alliance.house2_id == house1_id),
                ),
                Alliance.is_active == True,
            )
        )
        return result.scalars().first()

    async def break_alliances_for_war(self, attacker_high_lord_house_id: int):
        """Urush e'lon qilinganda ittifoqlarni buzish"""
        from datetime import datetime
        await self.session.execute(
            update(Alliance).where(
                or_(
                    Alliance.house1_id == attacker_high_lord_house_id,
                    Alliance.house2_id == attacker_high_lord_house_id,
                ),
                Alliance.is_active == True,
            ).values(is_active=False, broken_at=datetime.utcnow())
        )
        await self.session.commit()

    async def get_all_for_house(self, house_id: int) -> List[Alliance]:
        result = await self.session.execute(
            select(Alliance).where(
                or_(Alliance.house1_id == house_id, Alliance.house2_id == house_id),
                Alliance.is_active == True,
            ).options(selectinload(Alliance.house1), selectinload(Alliance.house2))
        )
        return result.scalars().all()

    async def get_all_active_for_house(self, house_id: int) -> List[Alliance]:
        """Xonadonning barcha faol ittifoqlari"""
        return await self.get_all_for_house(house_id)

    async def break_alliance(self, alliance_id: int):
        """Bitta ittifoqni buzish"""
        from datetime import datetime
        await self.session.execute(
            update(Alliance).where(Alliance.id == alliance_id)
            .values(is_active=False, broken_at=datetime.utcnow())
        )
        await self.session.commit()


class IronBankRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_house_active_debt(self, house_id: int) -> int:
        """Xonadonning to'lanmagan jami qarzi — lord almashsa ham tekshiriladi"""
        result = await self.session.execute(
            select(IronBankLoan).where(
                IronBankLoan.house_id == house_id,
                IronBankLoan.paid == False,
            )
        )
        loans = result.scalars().all()
        return sum(loan.total_due for loan in loans)

    async def create_loan(self, user_id: int, house_id: int, principal: int, rate: float, due_date) -> IronBankLoan:
        total = math.ceil(principal * (1 + rate))
        loan = IronBankLoan(
            user_id=user_id,
            house_id=house_id,
            principal=principal,
            interest_rate=rate,
            total_due=total,
            due_date=due_date,
        )
        self.session.add(loan)
        # Qarz xonadon xazinasiga tushadi
        await self.session.execute(
            update(House).where(House.id == house_id).values(
                treasury=House.treasury + principal,
            )
        )
        # Foydalanuvchi qarz miqdorini kuzatish uchun debt saqlanadi
        await self.session.execute(
            update(User).where(User.id == user_id).values(
                debt=User.debt + total,
            )
        )
        await self.session.commit()
        return loan

    async def repay(self, user: User, house_id: int, amount: int) -> dict:
        # Xazinada yetarli mablag' bormi?
        result = await self.session.execute(
            select(House).where(House.id == house_id)
        )
        house = result.scalar_one_or_none()
        if not house or house.treasury < amount:
            return {"success": False, "reason": "Xonadon xazinasida yetarli oltin yo'q"}

        # Xonadonning haqiqiy qarzi — IronBankLoan dan olamiz (lord almashsa ham to'g'ri)
        loans_result = await self.session.execute(
            select(IronBankLoan).where(
                IronBankLoan.house_id == house_id,
                IronBankLoan.paid == False,
            )
        )
        active_loans = loans_result.scalars().all()
        house_total_debt = sum(loan.total_due for loan in active_loans)

        if house_total_debt <= 0:
            return {"success": False, "reason": "Xonadonning faol qarzi yo'q"}

        actual = min(amount, house_total_debt)

        # Xazinadan ayirish
        await self.session.execute(
            update(House).where(House.id == house_id).values(
                treasury=House.treasury - actual,
            )
        )

        # Qarzlarni kamaytirish — eng eski qarzdan boshlab to'laymiz
        remaining_payment = actual
        for loan in sorted(active_loans, key=lambda l: l.id):
            if remaining_payment <= 0:
                break
            if loan.total_due <= remaining_payment:
                remaining_payment -= loan.total_due
                loan.total_due = 0
                loan.paid = True
            else:
                loan.total_due -= remaining_payment
                remaining_payment = 0

        new_debt = house_total_debt - actual

        # user.debt ni ham sinxronlashtirish (joriy lord uchun)
        await self.session.execute(
            update(User).where(User.id == user.id).values(
                debt=max(0, new_debt),
            )
        )

        await self.session.commit()
        return {"success": True, "paid": actual, "remaining": new_debt}

    async def get_all_active_loans(self) -> list:
        """Admin uchun — barcha to'lanmagan qarzlar"""
        result = await self.session.execute(
            select(IronBankLoan)
            .where(IronBankLoan.paid == False)
            .order_by(IronBankLoan.due_date)
        )
        return result.scalars().all()

    async def extend_due_date(self, house_id: int, days: int):
        """Qarz muddatini uzaytirish"""
        from datetime import timedelta
        await self.session.execute(
            update(IronBankLoan).where(
                IronBankLoan.house_id == house_id,
                IronBankLoan.paid == False,
            ).values(due_date=IronBankLoan.due_date + timedelta(days=days))
        )
        await self.session.commit()

    async def forgive_debt(self, house_id: int):
        """Qarzni to'liq kechirish"""
        await self.session.execute(
            update(IronBankLoan).where(
                IronBankLoan.house_id == house_id,
                IronBankLoan.paid == False,
            ).values(paid=True)
        )
        await self.session.execute(
            update(User).where(User.house_id == house_id).values(debt=0)
        )
        await self.session.commit()

    async def confiscate_partial(self, house_id: int, confiscate: dict) -> int:
        """
        Qisman musodara — admin tanlagan resurslarni olib qarz qoplamasiga hisoblaydi.
        confiscate = {soldiers, dragons, scorpions, gold} — nechta olinsin
        Qaytaradi: hisoblangan qoplama miqdori
        """
        from config.settings import settings as cfg
        # Qiymat hisoblash
        value = (
            confiscate.get("soldiers", 0) * cfg.SOLDIER_PRICE +
            confiscate.get("dragons", 0) * cfg.DRAGON_PRICE +
            confiscate.get("scorpions", 0) * cfg.SCORPION_PRICE +
            confiscate.get("gold", 0)
        )
        if value <= 0:
            return 0

        # Resurslarni ayirish
        await self.session.execute(
            update(House).where(House.id == house_id).values(
                total_soldiers=func.greatest(House.total_soldiers - confiscate.get("soldiers", 0), 0),
                total_dragons=func.greatest(House.total_dragons - confiscate.get("dragons", 0), 0),
                total_scorpions=func.greatest(House.total_scorpions - confiscate.get("scorpions", 0), 0),
                treasury=func.greatest(House.treasury - confiscate.get("gold", 0), 0),
            )
        )
        # Qarz kamaytirish
        result = await self.session.execute(
            select(User).where(
                User.house_id == house_id,
                User.role.in_([RoleEnum.LORD, RoleEnum.HIGH_LORD])
            )
        )
        lord = result.scalars().first()
        if lord:
            new_debt = max(0, lord.debt - value)
            await self.session.execute(
                update(User).where(User.id == lord.id).values(debt=new_debt)
            )
            if new_debt == 0:
                await self.session.execute(
                    update(IronBankLoan).where(
                        IronBankLoan.house_id == house_id,
                        IronBankLoan.paid == False,
                    ).values(paid=True)
                )
        await self.session.commit()
        return value

    async def confiscate_for_debt(self, user: User):
        """Qarz to'lanmasa — xonadon qo'shin, ajdar, skorpion va custom itemlari musodara"""
        if not user.house_id:
            return
        await self.session.execute(
            update(House).where(House.id == user.house_id).values(
                total_soldiers=0,
                total_dragons=0,
                total_scorpions=0,
            )
        )
        # Barcha a'zolarning shaxsiy qo'shinlarini ham nolga tushirish
        await self.session.execute(
            update(User).where(User.house_id == user.house_id).values(
                soldiers=0,
                dragons=0,
                scorpions=0,
                debt=0,
            )
        )
        # Custom itemlarni ham musodara qilish (xonadon va a'zolar)
        from database.models import HouseCustomItem, UserCustomItem
        from sqlalchemy import delete
        await self.session.execute(
            update(HouseCustomItem)
            .where(HouseCustomItem.house_id == user.house_id)
            .values(quantity=0)
        )
        # A'zolarning shaxsiy custom itemlarini ham nollaymiz
        user_ids_result = await self.session.execute(
            select(User.id).where(User.house_id == user.house_id)
        )
        uid_list = [r[0] for r in user_ids_result.all()]
        if uid_list:
            await self.session.execute(
                update(UserCustomItem)
                .where(UserCustomItem.user_id.in_(uid_list))
                .values(quantity=0)
            )
        # Qarzlarni yopish
        await self.session.execute(
            update(IronBankLoan).where(
                IronBankLoan.house_id == user.house_id,
                IronBankLoan.paid == False,
            ).values(paid=True)
        )
        await self.session.commit()


class ChronicleRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, event_type: str, description: str,
                  user_id: int = None, house_id: int = None,
                  tg_msg_id: int = None):
        entry = Chronicle(
            event_type=event_type,
            description=description,
            related_user_id=user_id,
            related_house_id=house_id,
            telegram_message_id=tg_msg_id,
        )
        self.session.add(entry)
        await self.session.commit()


class MarketRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_price(self, item_type: str) -> int:
        result = await self.session.execute(
            select(MarketPrice).where(MarketPrice.item_type == item_type)
        )
        mp = result.scalar_one_or_none()
        return mp.price if mp else 0

    async def set_price(self, item_type: str, price: int):
        await self.session.execute(
            update(MarketPrice).where(MarketPrice.item_type == item_type).values(price=price)
        )
        await self.session.commit()

    async def get_all_prices(self) -> dict:
        result = await self.session.execute(select(MarketPrice))
        items = result.scalars().all()
        return {item.item_type: item.price for item in items}


class BotSettingsRepo:
    """Admin sozlamalari — DB da saqlanadi, deploy da yo'qolmaydi"""

    DEFAULTS = {
        "interest_rate": "0.10",
        "bank_min_loan": "100",
        "bank_max_loan": "100000",
        "deposit_rate_per_day": "0.02",
        "deposit_duration_days": "7",
    }

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, key: str) -> str:
        from database.models import BotSettings
        result = await self.session.execute(
            select(BotSettings).where(BotSettings.key == key)
        )
        row = result.scalar_one_or_none()
        if row:
            return row.value
        return self.DEFAULTS.get(key, "")

    async def set(self, key: str, value: str):
        from database.models import BotSettings
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        # UPSERT
        stmt = pg_insert(BotSettings).values(key=key, value=value)
        stmt = stmt.on_conflict_do_update(index_elements=["key"], set_={"value": value})
        await self.session.execute(stmt)
        await self.session.commit()

    async def get_float(self, key: str) -> float:
        return float(await self.get(key))

    async def get_int(self, key: str) -> int:
        return int(await self.get(key))

    async def get_farm_schedules(self) -> list[dict]:
        """Farm jadvalini olish: [{"hour": 8, "minute": 0, "amount": 50}, ...]"""
        import json
        raw = await self.get("farm_schedules")
        if not raw:
            # Default: har kuni 08:00 da 50 tanga
            return [{"hour": 8, "minute": 0, "amount": 50}]
        try:
            return json.loads(raw)
        except Exception:
            return [{"hour": 8, "minute": 0, "amount": 50}]

    async def set_farm_schedules(self, schedules: list[dict]):
        """Farm jadvalini saqlash"""
        import json
        await self.set("farm_schedules", json.dumps(schedules))

    async def get_war_sessions(self) -> list[dict]:
        """
        Urush seanslarini olish.
        Format: [{"start": 19, "end": 23, "declare_deadline": 22}, ...]
        DB da yo'q bo'lsa — settings dan default qaytaradi.
        """
        import json
        from config.settings import settings as cfg
        raw = await self.get("war_sessions")
        if not raw:
            return [{
                "start": cfg.WAR_START_HOUR,
                "end": cfg.WAR_END_HOUR,
                "declare_deadline": cfg.WAR_DECLARE_DEADLINE,
            }]
        try:
            return json.loads(raw)
        except Exception:
            return [{
                "start": cfg.WAR_START_HOUR,
                "end": cfg.WAR_END_HOUR,
                "declare_deadline": cfg.WAR_DECLARE_DEADLINE,
            }]

    async def set_war_sessions(self, sessions: list[dict]):
        """Urush seanslarini saqlash"""
        import json
        await self.set("war_sessions", json.dumps(sessions))


class HukmdorClaimRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_active_claim(self, region) -> "Optional[HukmdorClaim]":
        from database.models import HukmdorClaim, ClaimStatusEnum
        result = await self.session.execute(
            select(HukmdorClaim).where(
                HukmdorClaim.region == region,
                HukmdorClaim.status.in_([ClaimStatusEnum.PENDING, ClaimStatusEnum.IN_PROGRESS])
            )
        )
        return result.scalars().first()

    async def create_claim(self, claimant_house_id: int, region) -> "HukmdorClaim":
        from database.models import HukmdorClaim, HukmdorClaimResponse, ClaimStatusEnum
        claim = HukmdorClaim(
            claimant_house_id=claimant_house_id,
            region=region,
            status=ClaimStatusEnum.PENDING,
        )
        self.session.add(claim)
        await self.session.flush()  # id olish uchun
        return claim

    async def add_response(self, claim_id: int, house_id: int) -> "HukmdorClaimResponse":
        from database.models import HukmdorClaimResponse
        resp = HukmdorClaimResponse(claim_id=claim_id, house_id=house_id)
        self.session.add(resp)
        await self.session.commit()
        return resp

    async def get_response(self, claim_id: int, house_id: int) -> "Optional[HukmdorClaimResponse]":
        from database.models import HukmdorClaimResponse
        result = await self.session.execute(
            select(HukmdorClaimResponse).where(
                HukmdorClaimResponse.claim_id == claim_id,
                HukmdorClaimResponse.house_id == house_id,
            )
        )
        return result.scalars().first()

    async def get_all_responses(self, claim_id: int) -> "List[HukmdorClaimResponse]":
        from database.models import HukmdorClaimResponse
        result = await self.session.execute(
            select(HukmdorClaimResponse).where(HukmdorClaimResponse.claim_id == claim_id)
        )
        return result.scalars().all()

    async def set_response(self, claim_id: int, house_id: int, accepted: bool):
        from database.models import HukmdorClaimResponse
        from datetime import datetime
        await self.session.execute(
            update(HukmdorClaimResponse).where(
                HukmdorClaimResponse.claim_id == claim_id,
                HukmdorClaimResponse.house_id == house_id,
            ).values(accepted=accepted, responded_at=datetime.utcnow())
        )
        await self.session.commit()

    async def set_status(self, claim_id: int, status):
        from database.models import HukmdorClaim
        from datetime import datetime
        vals = {"status": status}
        from database.models import ClaimStatusEnum
        if status == ClaimStatusEnum.COMPLETED:
            vals["resolved_at"] = datetime.utcnow()
        await self.session.execute(
            update(HukmdorClaim).where(HukmdorClaim.id == claim_id).values(**vals)
        )
        await self.session.commit()

    async def resolve_hukmdor(self, region, winner_house_id: int, bot):
        """G'olib xonadonini HIGH_LORD qilish, boshqalarni LORD ga tushirish"""
        from database.models import House, User, RoleEnum
        from sqlalchemy import select

        # Hududdagi barcha xonadonlar
        result = await self.session.execute(
            select(House).where(House.region == region)
        )
        houses = result.scalars().all()

        for house in houses:
            if house.id == winner_house_id:
                # G'olib xonadon — HIGH_LORD
                house.high_lord_id = house.lord_id
                if house.lord_id:
                    await self.session.execute(
                        update(User).where(User.id == house.lord_id)
                        .values(role=RoleEnum.HIGH_LORD)
                    )
                    try:
                        await bot.send_message(
                            house.lord_id,
                            f"👑 <b>TABRIKLAYMIZ!</b>\n\n"
                            f"Siz <b>{house.region.value}</b> hududining "
                            f"<b>HUKMDORI</b> bo'ldingiz!\n"
                            f"Barcha vassal xonadonlar sizga o'lpon to'laydi.",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
            else:
                # Mag'lub/vassal xonadonlar — HIGH_LORD ni o'chirish
                house.high_lord_id = None
                if house.lord_id:
                    await self.session.execute(
                        update(User).where(
                            User.id == house.lord_id,
                            User.role == RoleEnum.HIGH_LORD
                        ).values(role=RoleEnum.LORD)
                    )
                    try:
                        await bot.send_message(
                            house.lord_id,
                            f"🏰 Sizning xonadoningiz <b>{house.name}</b> "
                            f"vassal maqomini oldi.",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass

        await self.session.commit()


class RatingRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_power_ranking(self, limit: int = 1000) -> List[House]:
        """Umumiy kuch: askarlar + ajdarlar*200 + skorpionlar*25"""
        from sqlalchemy import text
        result = await self.session.execute(
            select(House)
            .order_by(
                (House.total_soldiers + House.total_dragons * 200 + House.total_scorpions * 25).desc()
            )
            .limit(limit)
        )
        return result.scalars().all()

    async def get_soldiers_ranking(self, limit: int = 1000) -> List[House]:
        """Askarlar soni bo'yicha"""
        result = await self.session.execute(
            select(House)
            .order_by(House.total_soldiers.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def get_gold_ranking(self, limit: int = 1000) -> List[House]:
        """Xonadon xazinasi bo'yicha"""
        result = await self.session.execute(
            select(House)
            .order_by(House.treasury.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def get_dragons_ranking(self, limit: int = 1000) -> List[House]:
        """Ajdarlar + Skorpionlar bo'yicha"""
        result = await self.session.execute(
            select(House)
            .order_by(House.total_dragons.desc(), House.total_scorpions.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def get_wins_ranking(self, limit: int = 1000) -> List[tuple]:
        """Urushda g'alaba soniga ko'ra xonadonlar reytingi"""
        result = await self.session.execute(
            select(House.name, func.count(War.id).label("wins"))
            .join(War, War.winner_house_id == House.id)
            .where(War.status == WarStatusEnum.ENDED)
            .group_by(House.id, House.name)
            .order_by(func.count(War.id).desc())
            .limit(limit)
        )
        return result.all()


class CustomItemRepo:
    """Maxsus itemlar bilan ishlash"""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ── Admin: item boshqaruvi ─────────────────────────────────────────────

    async def create_item(
        self, name: str, emoji: str, item_type, attack_power: int,
        defense_power: int, price: int, max_stock: int = None
    ):
        from database.models import CustomItem
        item = CustomItem(
            name=name, emoji=emoji, item_type=item_type,
            attack_power=attack_power, defense_power=defense_power,
            price=price, is_active=True,
            max_stock=max_stock,
            stock_remaining=max_stock,  # Boshida max_stock bilan teng
        )
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def get_all_active(self):
        from database.models import CustomItem
        result = await self.session.execute(
            select(CustomItem).where(CustomItem.is_active == True)
        )
        return result.scalars().all()

    async def get_all(self):
        from database.models import CustomItem
        result = await self.session.execute(select(CustomItem))
        return result.scalars().all()

    async def get_by_id(self, item_id: int):
        from database.models import CustomItem
        result = await self.session.execute(
            select(CustomItem).where(CustomItem.id == item_id)
        )
        return result.scalar_one_or_none()

    async def update_item(self, item_id: int, **kwargs):
        """Item maydonlarini yangilash (attack_power, defense_power, price, max_stock, stock_remaining)"""
        from database.models import CustomItem
        allowed = {"attack_power", "defense_power", "price", "max_stock", "stock_remaining"}
        values = {k: v for k, v in kwargs.items() if k in allowed}
        if not values:
            return
        await self.session.execute(
            update(CustomItem).where(CustomItem.id == item_id).values(**values)
        )
        await self.session.commit()

    async def reduce_stock(self, item_id: int, qty: int) -> bool:
        """Stokni kamaytirish. Yetarli stok bo'lmasa False qaytaradi."""
        from database.models import CustomItem
        result = await self.session.execute(
            select(CustomItem).where(CustomItem.id == item_id)
        )
        item = result.scalar_one_or_none()
        if not item:
            return False
        # Cheksiz stok
        if item.stock_remaining is None:
            return True
        if item.stock_remaining < qty:
            return False
        item.stock_remaining -= qty
        await self.session.commit()
        return True

    async def toggle_active(self, item_id: int):
        from database.models import CustomItem
        result = await self.session.execute(
            select(CustomItem).where(CustomItem.id == item_id)
        )
        item = result.scalar_one_or_none()
        if item:
            item.is_active = not item.is_active
            await self.session.commit()
        return item

    async def delete_item(self, item_id: int):
        from database.models import CustomItem, UserCustomItem, HouseCustomItem
        await self.session.execute(
            select(UserCustomItem).where(UserCustomItem.item_id == item_id)
        )
        # Cascade o'chirish
        from sqlalchemy import delete
        await self.session.execute(
            delete(UserCustomItem).where(UserCustomItem.item_id == item_id)
        )
        await self.session.execute(
            delete(HouseCustomItem).where(HouseCustomItem.item_id == item_id)
        )
        await self.session.execute(
            delete(CustomItem).where(CustomItem.id == item_id)
        )
        await self.session.commit()

    # ── Foydalanuvchi: sotib olish ─────────────────────────────────────────

    async def get_user_items(self, user_id: int):
        from database.models import UserCustomItem
        result = await self.session.execute(
            select(UserCustomItem).where(
                UserCustomItem.user_id == user_id,
                UserCustomItem.quantity > 0,
            )
        )
        return result.scalars().all()

    async def add_user_item(self, user_id: int, item_id: int, qty: int):
        from database.models import UserCustomItem
        result = await self.session.execute(
            select(UserCustomItem).where(
                UserCustomItem.user_id == user_id,
                UserCustomItem.item_id == item_id,
            )
        )
        row = result.scalar_one_or_none()
        if row:
            row.quantity += qty
        else:
            row = UserCustomItem(user_id=user_id, item_id=item_id, quantity=qty)
            self.session.add(row)
        await self.session.commit()

    # ── Xonadon: umumiy hisob ─────────────────────────────────────────────

    async def get_house_items(self, house_id: int):
        from database.models import HouseCustomItem
        result = await self.session.execute(
            select(HouseCustomItem).where(
                HouseCustomItem.house_id == house_id,
                HouseCustomItem.quantity > 0,
            )
        )
        return result.scalars().all()

    async def add_house_item(self, house_id: int, item_id: int, qty: int):
        from database.models import HouseCustomItem
        result = await self.session.execute(
            select(HouseCustomItem).where(
                HouseCustomItem.house_id == house_id,
                HouseCustomItem.item_id == item_id,
            )
        )
        row = result.scalar_one_or_none()
        if row:
            row.quantity = max(0, row.quantity + qty)
        else:
            if qty > 0:
                row = HouseCustomItem(house_id=house_id, item_id=item_id, quantity=qty)
                self.session.add(row)
        await self.session.commit()

    async def get_house_items_with_info(self, house_id: int):
        """House itemlarini CustomItem ma'lumotlari bilan birga qaytaradi"""
        from database.models import HouseCustomItem, CustomItem
        from sqlalchemy.orm import selectinload
        result = await self.session.execute(
            select(HouseCustomItem)
            .options(selectinload(HouseCustomItem.item))
            .where(
                HouseCustomItem.house_id == house_id,
                HouseCustomItem.quantity > 0,
            )
        )
        return result.scalars().all()

    async def get_user_items_with_info(self, user_id: int):
        """Foydalanuvchi itemlarini CustomItem ma'lumotlari bilan birga qaytaradi"""
        from database.models import UserCustomItem
        from sqlalchemy.orm import selectinload
        result = await self.session.execute(
            select(UserCustomItem)
            .options(selectinload(UserCustomItem.item))
            .where(
                UserCustomItem.user_id == user_id,
                UserCustomItem.quantity > 0,
            )
        )
        return result.scalars().all()


class AllianceGroupRepo:
    """Ittifoq guruhlari bilan ishlash"""

    MAX_MEMBERS = 3  # Tashkilotchi + 2 ta a'zo (faqat bir hududdan)

    def __init__(self, session: AsyncSession):
        self.session = session

    # ── Mavjudlik tekshiruvlari ──────────────────────────────────────────

    async def get_house_active_group(self, house_id: int) -> Optional[AllianceGroup]:
        """Xonadon qaysi faol guruhda ekanligini qaytaradi"""
        result = await self.session.execute(
            select(AllianceGroup)
            .join(AllianceGroupMember, AllianceGroupMember.group_id == AllianceGroup.id)
            .where(
                AllianceGroupMember.house_id == house_id,
                AllianceGroup.is_active == True,
            )
            .options(
                selectinload(AllianceGroup.members).selectinload(AllianceGroupMember.house),
                selectinload(AllianceGroup.leader_house),
            )
        )
        return result.scalars().first()

    async def get_group_by_id(self, group_id: int) -> Optional[AllianceGroup]:
        result = await self.session.execute(
            select(AllianceGroup)
            .where(AllianceGroup.id == group_id, AllianceGroup.is_active == True)
            .options(
                selectinload(AllianceGroup.members).selectinload(AllianceGroupMember.house),
                selectinload(AllianceGroup.leader_house),
            )
        )
        return result.scalars().first()

    async def get_pending_invite(self, group_id: int, to_house_id: int) -> Optional[AllianceGroupInvite]:
        result = await self.session.execute(
            select(AllianceGroupInvite).where(
                AllianceGroupInvite.group_id == group_id,
                AllianceGroupInvite.to_house_id == to_house_id,
                AllianceGroupInvite.status == "pending",
            )
        )
        return result.scalars().first()

    async def get_invite_by_id(self, invite_id: int) -> Optional[AllianceGroupInvite]:
        result = await self.session.execute(
            select(AllianceGroupInvite)
            .where(AllianceGroupInvite.id == invite_id)
            .options(
                selectinload(AllianceGroupInvite.group).selectinload(AllianceGroup.members),
                selectinload(AllianceGroupInvite.from_house),
                selectinload(AllianceGroupInvite.to_house),
            )
        )
        return result.scalars().first()

    # ── Guruh yaratish ───────────────────────────────────────────────────

    async def create_group(self, name: str, leader_house_id: int) -> AllianceGroup:
        """Yangi ittifoq guruhi yaratish — tashkilotchi avtomatik a'zo bo'ladi"""
        group = AllianceGroup(name=name, leader_house_id=leader_house_id)
        self.session.add(group)
        await self.session.flush()  # group.id kerak
        member = AllianceGroupMember(group_id=group.id, house_id=leader_house_id)
        self.session.add(member)
        await self.session.commit()
        await self.session.refresh(group)
        return group

    # ── Taklif yuborish / qabul / rad ───────────────────────────────────

    async def send_invite(self, group_id: int, from_house_id: int, to_house_id: int) -> AllianceGroupInvite:
        invite = AllianceGroupInvite(
            group_id=group_id,
            from_house_id=from_house_id,
            to_house_id=to_house_id,
        )
        self.session.add(invite)
        await self.session.commit()
        return invite

    async def accept_invite(self, invite_id: int) -> bool:
        """Taklifni qabul qilish va guruhga qo'shish. False = joy to'liq"""
        invite = await self.get_invite_by_id(invite_id)
        if not invite or invite.status != "pending":
            return False

        group = await self.get_group_by_id(invite.group_id)
        if not group:
            return False

        if len(group.members) >= self.MAX_MEMBERS:
            invite.status = "rejected"
            await self.session.commit()
            return False

        invite.status = "accepted"
        member = AllianceGroupMember(group_id=invite.group_id, house_id=invite.to_house_id)
        self.session.add(member)
        await self.session.commit()
        return True

    async def reject_invite(self, invite_id: int):
        result = await self.session.execute(
            select(AllianceGroupInvite).where(AllianceGroupInvite.id == invite_id)
        )
        invite = result.scalars().first()
        if invite:
            invite.status = "rejected"
            await self.session.commit()

    # ── Guruhni tarqatish / a'zolikdan chiqish ──────────────────────────

    async def disband_group(self, group_id: int):
        """Guruhni to'liq tarqatish (faqat tashkilotchi)"""
        from datetime import datetime
        await self.session.execute(
            update(AllianceGroup)
            .where(AllianceGroup.id == group_id)
            .values(is_active=False, disbanded_at=datetime.utcnow())
        )
        await self.session.commit()

    async def leave_group(self, group_id: int, house_id: int):
        """A'zo xonadon guruhdan chiqadi"""
        from sqlalchemy import delete as sa_delete
        await self.session.execute(
            sa_delete(AllianceGroupMember).where(
                AllianceGroupMember.group_id == group_id,
                AllianceGroupMember.house_id == house_id,
            )
        )
        await self.session.commit()

    # ── Nom o'zgartirish ─────────────────────────────────────────────────

    async def rename_group(self, group_id: int, new_name: str):
        await self.session.execute(
            update(AllianceGroup)
            .where(AllianceGroup.id == group_id)
            .values(name=new_name)
        )
        await self.session.commit()

    # ── Reyting uchun ────────────────────────────────────────────────────

    async def get_alliance_power_ranking(self, limit: int = 10) -> List[dict]:
        """
        Har bir faol ittifoq guruhining umumiy kuchini hisoblaydi.
        Kuch = barcha a'zo xonadonlarning soldiers + dragons*200 + scorpions*25
        """
        result = await self.session.execute(
            select(AllianceGroup)
            .where(AllianceGroup.is_active == True)
            .options(
                selectinload(AllianceGroup.members).selectinload(AllianceGroupMember.house),
                selectinload(AllianceGroup.leader_house),
            )
        )
        groups = result.scalars().all()

        ranking = []
        for group in groups:
            total_soldiers = 0
            total_dragons = 0
            total_scorpions = 0
            total_treasury = 0
            member_names = []
            for m in group.members:
                h = m.house
                if h:
                    total_soldiers += h.total_soldiers
                    total_dragons += h.total_dragons
                    total_scorpions += h.total_scorpions
                    total_treasury += h.treasury
                    member_names.append(h.name)
            power = total_soldiers + total_dragons * 200 + total_scorpions * 25
            ranking.append({
                "group": group,
                "power": power,
                "total_soldiers": total_soldiers,
                "total_dragons": total_dragons,
                "total_scorpions": total_scorpions,
                "total_treasury": total_treasury,
                "member_names": member_names,
                "member_count": len(group.members),
            })

        ranking.sort(key=lambda x: x["power"], reverse=True)
        return ranking[:limit]


class IronBankDepositRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, house_id: int, gold: int, soldiers: int, dragons: int,
                     scorpions: int, rate_per_day: float, duration_days: int) -> "IronBankDeposit":
        from database.models import IronBankDeposit
        from datetime import datetime, timedelta
        expires_at = datetime.utcnow() + timedelta(days=duration_days)
        dep = IronBankDeposit(
            house_id=house_id,
            gold=gold,
            soldiers=soldiers,
            dragons=dragons,
            scorpions=scorpions,
            interest_rate_per_day=rate_per_day,
            duration_days=duration_days,
            expires_at=expires_at,
        )
        self.session.add(dep)
        await self.session.commit()
        await self.session.refresh(dep)
        return dep

    async def get_active(self, house_id: int) -> "Optional[IronBankDeposit]":
        from database.models import IronBankDeposit
        result = await self.session.execute(
            select(IronBankDeposit).where(
                IronBankDeposit.house_id == house_id,
                IronBankDeposit.is_active == True,
            )
        )
        return result.scalar_one_or_none()

    async def get_all_active(self) -> list:
        from database.models import IronBankDeposit
        result = await self.session.execute(
            select(IronBankDeposit).where(IronBankDeposit.is_active == True)
        )
        return result.scalars().all()

    async def close(self, deposit: "IronBankDeposit", pay_interest: bool = True):
        """Omonatni yopish — resurslarni qaytarish + foiz to'lash"""
        from database.models import IronBankDeposit
        from datetime import datetime
        import math

        deposit.is_active = False
        deposit.closed_at = datetime.utcnow()

        # Kunlar sonini hisoblash (haqiqiy turgan vaqt, max muddat)
        days_held = (datetime.utcnow() - deposit.created_at).days
        days_held = min(days_held, deposit.duration_days)

        # Foiz faqat oltinga (xazinaga)
        if pay_interest and days_held > 0:
            interest = math.floor(deposit.gold * deposit.interest_rate_per_day * days_held)
        else:
            interest = 0

        # Resurslarni xonadonga qaytarish
        await self.session.execute(
            update(House).where(House.id == deposit.house_id).values(
                treasury=House.treasury + deposit.gold + interest,
                total_soldiers=House.total_soldiers + deposit.soldiers,
                total_dragons=House.total_dragons + deposit.dragons,
                total_scorpions=House.total_scorpions + deposit.scorpions,
            )
        )
        await self.session.commit()
        return interest

    async def pay_daily_interest(self, deposit: "IronBankDeposit"):
        """Kunlik foizni to'g'ridan-to'g'ri xazinaga o'tkazish"""
        import math
        interest = math.floor(deposit.gold * deposit.interest_rate_per_day)
        if interest > 0:
            await self.session.execute(
                update(House).where(House.id == deposit.house_id).values(
                    treasury=House.treasury + interest,
                )
            )
            await self.session.commit()
        return interest
