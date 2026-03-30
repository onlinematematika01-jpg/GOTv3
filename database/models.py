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
    ADMIN = "admin"           # Uch ko'zli qarg'a
    HIGH_LORD = "high_lord"  # Hukmdor Vassal (Oliy Lord)
    LORD = "lord"             # Vassal Lordi
    MEMBER = "member"         # A'zo


class WarStatusEnum(str, enum.Enum):
    DECLARED = "declared"
    GRACE_PERIOD = "grace_period"
    FIGHTING = "fighting"
    ENDED = "ended"


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True)  # Telegram user_id
    username = Column(String(64), nullable=True)
    full_name = Column(String(128), nullable=False)
    role = Column(Enum(RoleEnum), default=RoleEnum.MEMBER, nullable=False)
    region = Column(Enum(RegionEnum), nullable=True)
    house_id = Column(Integer, ForeignKey("houses.id"), nullable=True)
    gold = Column(BigInteger, default=0)
    soldiers = Column(Integer, default=0)
    dragons = Column(Integer, default=0)
    scorpions = Column(Integer, default=0)
    is_exiled = Column(Boolean, default=False)
    referral_by = Column(BigInteger, ForeignKey("users.id"), nullable=True)
    referral_count_today = Column(Integer, default=0)
    last_farm_date = Column(DateTime, nullable=True)
    last_referral_reset = Column(DateTime, nullable=True)
    debt = Column(BigInteger, default=0)  # Iron Bank qarzi
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())

    house = relationship("House", back_populates="members", foreign_keys=[house_id])
    sent_messages = relationship("InternalMessage", foreign_keys="InternalMessage.sender_id", back_populates="sender")


class House(Base):
    __tablename__ = "houses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    region = Column(Enum(RegionEnum), nullable=False, unique=True)
    lord_id = Column(BigInteger, ForeignKey("users.id"), nullable=True)
    high_lord_id = Column(BigInteger, ForeignKey("users.id"), nullable=True)
    treasury = Column(BigInteger, default=0)  # Xonadon xazinasi
    total_soldiers = Column(Integer, default=0)
    total_dragons = Column(Integer, default=0)
    total_scorpions = Column(Integer, default=0)
    is_under_occupation = Column(Boolean, default=False)
    occupier_house_id = Column(Integer, ForeignKey("houses.id"), nullable=True)
    permanent_tax_rate = Column(Float, default=0.0)  # Taslim bo'lgandan keyingi soliq
    created_at = Column(DateTime, server_default=func.now())

    members = relationship("User", back_populates="house", foreign_keys=[User.house_id])
    lord = relationship("User", foreign_keys=[lord_id])
    high_lord = relationship("User", foreign_keys=[high_lord_id])


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


class IronBankLoan(Base):
    __tablename__ = "iron_bank_loans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
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
    item_type = Column(String(32), nullable=False, unique=True)  # soldier, dragon, scorpion
    price = Column(Integer, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class BotSettings(Base):
    """Admin tomonidan o'zgartiriluvchi sozlamalar — DB da saqlanadi, deploy da yo'qolmaydi"""
    __tablename__ = "bot_settings"

    key = Column(String(64), primary_key=True)
    value = Column(String(256), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
