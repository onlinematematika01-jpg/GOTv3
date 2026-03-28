from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func, and_, or_
from sqlalchemy.orm import selectinload
from database.models import (
    User, House, Alliance, War, IronBankLoan,
    InternalMessage, Chronicle, MarketPrice,
    RoleEnum, RegionEnum, WarStatusEnum
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

    async def update_gold(self, user_id: int, amount: int):
        await self.session.execute(
            update(User).where(User.id == user_id).values(gold=User.gold + amount)
        )
        await self.session.commit()

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
        """Eng ko'p oltin to'plagan a'zo (keyingi lord uchun)"""
        result = await self.session.execute(
            select(User).where(
                User.house_id == house_id,
                User.role == RoleEnum.MEMBER,
                User.id != exclude_id,
                User.is_active == True
            ).order_by(User.gold.desc())
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

    async def update_treasury(self, house_id: int, amount: int):
        await self.session.execute(
            update(House).where(House.id == house_id)
            .values(treasury=House.treasury + amount)
        )
        await self.session.commit()

    async def update_military(self, house_id: int, soldiers: int = 0, dragons: int = 0, scorpions: int = 0):
        await self.session.execute(
            update(House).where(House.id == house_id).values(
                total_soldiers=House.total_soldiers + soldiers,
                total_dragons=House.total_dragons + dragons,
                total_scorpions=House.total_scorpions + scorpions,
            )
        )
        await self.session.commit()

    async def set_occupation(self, house_id: int, occupier_id: int, tax_rate: float):
        await self.session.execute(
            update(House).where(House.id == house_id).values(
                is_under_occupation=True,
                occupier_house_id=occupier_id,
                permanent_tax_rate=tax_rate,
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
        result = await self.session.execute(
            select(War).where(
                War.status.in_([WarStatusEnum.GRACE_PERIOD, WarStatusEnum.FIGHTING])
            ).options(selectinload(War.attacker), selectinload(War.defender))
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


class IronBankRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_loan(self, user_id: int, principal: int, rate: float, due_date) -> IronBankLoan:
        total = math.ceil(principal * (1 + rate))
        loan = IronBankLoan(
            user_id=user_id,
            principal=principal,
            interest_rate=rate,
            total_due=total,
            due_date=due_date,
        )
        self.session.add(loan)
        await self.session.execute(
            update(User).where(User.id == user_id).values(
                gold=User.gold + principal,
                debt=User.debt + total,
            )
        )
        await self.session.commit()
        return loan

    async def repay(self, user: User, amount: int) -> dict:
        if user.gold < amount:
            return {"success": False, "reason": "Yetarli oltin yo'q"}
        actual = min(amount, user.debt)
        await self.session.execute(
            update(User).where(User.id == user.id).values(
                gold=User.gold - actual,
                debt=User.debt - actual,
            )
        )
        await self.session.commit()
        return {"success": True, "paid": actual, "remaining": user.debt - actual}

    async def confiscate_for_debt(self, user: User):
        """Qarz to'lanmasa — qo'shin va ajdarlar musodara"""
        await self.session.execute(
            update(User).where(User.id == user.id).values(
                soldiers=0,
                dragons=0,
                debt=0,
            )
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
