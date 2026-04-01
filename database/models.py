from sqlalchemy import (
    Column, Integer, BigInteger, String, Float, Boolean,
    DateTime, ForeignKey, Enum, Text, func
)
from sqlalchemy.orm import relationship, DeclarativeBase
import enum


class Base(DeclarativeBase):
    pass


class RegionEnum(str, enum.Enum):
    NORTH = "Shimol"
    VALE = "Vodiy"
    RIVERLANDS = "Daryo yerlari"
    IRON_ISLANDS = "Temir orollar"
    WESTERLANDS = "G'arbiy yerlar"
    KINGS_LANDING = "Qirollik bandargohi"
    REACH = "Tyrellar vodiysi"
    STORMLANDS = "Bo'ronli yerlar"
    DORNE = "Dorn"


class RoleEnum(str, enum.Enum):
    ADMIN = "admin"
    HIGH_LORD = "high_lord"
    LORD = "lord"
    MEMBER = "member"


class WarStatusEnum(str, enum.Enum):
    DECLARED = "declared"
    GRACE_PERIOD = "grace_period"
    FIGHTING = "fighting"
    ENDED = "ended"


class WarTypeEnum(str, enum.Enum):
    EXTERNAL = "external"   # Boshqa hududga urush
    CIVIL = "civil"         # Bir hududdagi xonadonlar o'rtasida Hukmdorlik uchun


class ClaimStatusEnum(str, enum.Enum):
    PENDING = "pending"       # Boshqa xonadonlar javob kutmoqda
    IN_PROGRESS = "in_progress"  # Urushlar ketmoqda
    COMPLETED = "completed"   # Hukmdor belgilandi


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True)
    username = Column(String(64), nullable=True)
    full_name = Column(String(128), nullable=False)
    role = Column(Enum(RoleEnum), default=RoleEnum.MEMBER, nullable=False)
    region = Column(Enum(RegionEnum), nullable=True)
    house_id = Column(Integer, ForeignKey("houses.id"), nullable=True)
    soldiers = Column(Integer, default=0)
    dragons = Column(Integer, default=0)
    scorpions = Column(Integer, default=0)
    is_exiled = Column(Boolean, default=False)
    referral_by = Column(BigInteger, ForeignKey("users.id"), nullable=True)
    referral_count_today = Column(Integer, default=0)
    last_farm_date = Column(DateTime, nullable=True)
    last_referral_reset = Column(DateTime, nullable=True)
    debt = Column(BigInteger, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())

    house = relationship("House", back_populates="members", foreign_keys=[house_id])
    sent_messages = relationship("InternalMessage", foreign_keys="InternalMessage.sender_id", back_populates="sender")


class House(Base):
    __tablename__ = "houses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    region = Column(Enum(RegionEnum), nullable=False)
    lord_id = Column(BigInteger, ForeignKey("users.id"), nullable=True)
    high_lord_id = Column(BigInteger, ForeignKey("users.id"), nullable=True)
    treasury = Column(BigInteger, default=0)
    total_soldiers = Column(Integer, default=0)
    total_dragons = Column(Integer, default=0)
    total_scorpions = Column(Integer, default=0)
    is_under_occupation = Column(Boolean, default=False)
    occupier_house_id = Column(Integer, ForeignKey("houses.id"), nullable=True)
    permanent_tax_rate = Column(Float, default=0.0)
    vassal_since = Column(DateTime, nullable=True)  # Vassal bo'lgan sana — isyon sanasi hisoblash uchun
    created_at = Column(DateTime, server_default=func.now())

    members = relationship("User", back_populates="house", foreign_keys=[User.house_id])
    lord = relationship("User", foreign_keys=[lord_id])
    high_lord = relationship("User", foreign_keys=[high_lord_id])


class HukmdorClaim(Base):
    """Bir hududdagi Hukmdorlik da'vosi jarayoni"""
    __tablename__ = "hukmdor_claims"

    id = Column(Integer, primary_key=True, autoincrement=True)
    claimant_house_id = Column(Integer, ForeignKey("houses.id"), nullable=False)
    region = Column(Enum(RegionEnum), nullable=False)
    status = Column(Enum(ClaimStatusEnum), default=ClaimStatusEnum.PENDING)
    created_at = Column(DateTime, server_default=func.now())
    resolved_at = Column(DateTime, nullable=True)

    claimant = relationship("House", foreign_keys=[claimant_house_id])


class HukmdorClaimResponse(Base):
    """Boshqa xonadonlarning da'voga javobi"""
    __tablename__ = "hukmdor_claim_responses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    claim_id = Column(Integer, ForeignKey("hukmdor_claims.id"), nullable=False)
    house_id = Column(Integer, ForeignKey("houses.id"), nullable=False)
    accepted = Column(Boolean, nullable=True)  # None=javob kutilmoqda, True=qabul, False=rad
    responded_at = Column(DateTime, nullable=True)

    claim = relationship("HukmdorClaim")
    house = relationship("House", foreign_keys=[house_id])


class Alliance(Base):
    __tablename__ = "alliances"

    id = Column(Integer, primary_key=True, autoincrement=True)
    house1_id = Column(Integer, ForeignKey("houses.id"), nullable=False)
    house2_id = Column(Integer, ForeignKey("houses.id"), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    broken_at = Column(DateTime, nullable=True)

    house1 = relationship("House", foreign_keys=[house1_id])
    house2 = relationship("House", foreign_keys=[house2_id])


class War(Base):
    __tablename__ = "wars"

    id = Column(Integer, primary_key=True, autoincrement=True)
    attacker_house_id = Column(Integer, ForeignKey("houses.id"), nullable=False)
    defender_house_id = Column(Integer, ForeignKey("houses.id"), nullable=False)
    war_type = Column(String(16), default=WarTypeEnum.EXTERNAL.value)
    claim_id = Column(Integer, ForeignKey("hukmdor_claims.id"), nullable=True)  # Civil urush uchun
    status = Column(Enum(WarStatusEnum), default=WarStatusEnum.DECLARED)
    declared_at = Column(DateTime, server_default=func.now())
    grace_ends_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    winner_house_id = Column(Integer, ForeignKey("houses.id"), nullable=True)
    attacker_soldiers_lost = Column(Integer, default=0)
    defender_soldiers_lost = Column(Integer, default=0)
    attacker_dragons_lost = Column(Integer, default=0)
    defender_dragons_lost = Column(Integer, default=0)
    loot_gold = Column(BigInteger, default=0)
    defender_surrendered = Column(Boolean, default=False)

    attacker = relationship("House", foreign_keys=[attacker_house_id])
    defender = relationship("House", foreign_keys=[defender_house_id])
    winner = relationship("House", foreign_keys=[winner_house_id])


class WarAllySupport(Base):
    """Urushda ittifoqchi yordami"""
    __tablename__ = "war_ally_supports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    war_id = Column(Integer, ForeignKey("wars.id"), nullable=False)
    ally_house_id = Column(Integer, ForeignKey("houses.id"), nullable=False)
    side = Column(String(16), nullable=False)      # "attacker" | "defender"
    join_type = Column(String(16), nullable=False) # "full" | "soldiers" | "gold"
    soldiers = Column(Integer, default=0)
    dragons = Column(Integer, default=0)
    scorpions = Column(Integer, default=0)
    gold = Column(BigInteger, default=0)           # yuborilgan oltin miqdori
    created_at = Column(DateTime, server_default=func.now())

    war = relationship("War", foreign_keys=[war_id])
    ally_house = relationship("House", foreign_keys=[ally_house_id])


class IronBankLoan(Base):
    __tablename__ = "iron_bank_loans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    house_id = Column(Integer, ForeignKey("houses.id"), nullable=True)  # qarz olgan xonadon
    principal = Column(BigInteger, nullable=False)
    interest_rate = Column(Float, nullable=False)
    total_due = Column(BigInteger, nullable=False)
    paid = Column(Boolean, default=False)
    due_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User")


class InternalMessage(Base):
    __tablename__ = "internal_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sender_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    house_id = Column(Integer, ForeignKey("houses.id"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    sender = relationship("User", foreign_keys=[sender_id], back_populates="sent_messages")
    house = relationship("House")


class Chronicle(Base):
    __tablename__ = "chronicles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(64), nullable=False)
    description = Column(Text, nullable=False)
    related_user_id = Column(BigInteger, nullable=True)
    related_house_id = Column(Integer, nullable=True)
    telegram_message_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class MarketPrice(Base):
    __tablename__ = "market_prices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_type = Column(String(32), nullable=False, unique=True)
    price = Column(Integer, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class BotSettings(Base):
    __tablename__ = "bot_settings"

    key = Column(String(64), primary_key=True)
    value = Column(String(256), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
