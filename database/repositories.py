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
        actual = min(amount, user.debt)
        await self.session.execute(
            update(House).where(House.id == house_id).values(
                treasury=House.treasury - actual,
            )
        )
        new_debt = user.debt - actual
        await self.session.execute(
            update(User).where(User.id == user.id).values(
                debt=new_debt,
            )
        )
        # Qarz to'liq to'langan bo'lsa — IronBankLoan ni paid=True qilish
        if new_debt <= 0:
            await self.session.execute(
                update(IronBankLoan).where(
                    IronBankLoan.house_id == house_id,
                    IronBankLoan.paid == False,
                ).values(paid=True)
            )
        await self.session.commit()
        return {"success": True, "paid": actual, "remaining": new_debt}

    async def confiscate_for_debt(self, user: User):
        """Qarz to'lanmasa — xonadon qo'shin va ajdarlari musodara"""
        if not user.house_id:
            return
        await self.session.execute(
            update(House).where(House.id == user.house_id).values(
                total_soldiers=0,
                total_dragons=0,
            )
        )
        # Barcha a'zolarning shaxsiy qo'shinlarini ham nolga tushirish
        await self.session.execute(
            update(User).where(User.house_id == user.house_id).values(
                soldiers=0,
                dragons=0,
                debt=0,
            )
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

    async def get_power_ranking(self, limit: int = 10) -> List[House]:
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

    async def get_soldiers_ranking(self, limit: int = 10) -> List[House]:
        """Askarlar soni bo'yicha"""
        result = await self.session.execute(
            select(House)
            .order_by(House.total_soldiers.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def get_gold_ranking(self, limit: int = 10) -> List[House]:
        """Xonadon xazinasi bo'yicha"""
        result = await self.session.execute(
            select(House)
            .order_by(House.treasury.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def get_dragons_ranking(self, limit: int = 10) -> List[House]:
        """Ajdarlar + Skorpionlar bo'yicha"""
        result = await self.session.execute(
            select(House)
            .order_by(House.total_dragons.desc(), House.total_scorpions.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def get_wins_ranking(self, limit: int = 10) -> List[tuple]:
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
