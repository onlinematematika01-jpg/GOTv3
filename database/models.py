from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Float, ForeignKey,
    Integer, String, Text, func
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import ENUM


class Base(DeclarativeBase):
    pass


# ── Enums ─────────────────────────────────────────────────────────────────────

class UserRole(str, PyEnum):
    admin      = "admin"
    high_lord  = "high_lord"
    lord       = "lord"
    member     = "member"


class Region(str, PyEnum):
    north       = "north"
    vale        = "vale"
    stormlands  = "stormlands"
    reach       = "reach"
    westerlands = "westerlands"
    riverlands  = "riverlands"
    iron_islands = "iron_islands"
    dorne       = "dorne"
    crownlands  = "crownlands"


class WarStatus(str, PyEnum):
    grace_period = "grace_period"
    fighting     = "fighting"
    ended        = "ended"


class AllianceStatus(str, PyEnum):
    active    = "active"
    dissolved = "dissolved"


class ClaimStatus(str, PyEnum):
    pending  = "pending"
    accepted = "accepted"
    rejected = "rejected"
    war      = "war"
    won      = "won"
    lost     = "lost"


class LoanStatus(str, PyEnum):
    active    = "active"
    paid      = "paid"
    defaulted = "defaulted"


# ── Models ────────────────────────────────────────────────────────────────────

class House(Base):
    __tablename__ = "houses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    region: Mapped[Region] = mapped_column(
        ENUM(Region, name="region_enum", create_type=False), nullable=False
    )
    lord_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", use_alter=True), nullable=True
    )
    high_lord_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", use_alter=True), nullable=True
    )
    treasury: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_soldiers: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_dragons: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_scorpions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_under_occupation: Mapped[bool] = mapped_column(Boolean, default=False)
    occupier_house_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("houses.id"), nullable=True
    )
    permanent_tax_rate: Mapped[float] = mapped_column(Float, default=0.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram user ID
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        ENUM(UserRole, name="userrole_enum", create_type=False),
        default=UserRole.member
    )
    region: Mapped[Region | None] = mapped_column(
        ENUM(Region, name="region_enum", create_type=False), nullable=True
    )
    house_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("houses.id"), nullable=True
    )
    soldiers: Mapped[int] = mapped_column(Integer, default=0)
    dragons: Mapped[int] = mapped_column(Integer, default=0)
    scorpions: Mapped[int] = mapped_column(Integer, default=0)
    debt: Mapped[int] = mapped_column(BigInteger, default=0)
    is_exiled: Mapped[bool] = mapped_column(Boolean, default=False)
    referral_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=True
    )
    referral_count_today: Mapped[int] = mapped_column(Integer, default=0)
    last_farm_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class War(Base):
    __tablename__ = "wars"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    attacker_house_id: Mapped[int] = mapped_column(Integer, ForeignKey("houses.id"))
    defender_house_id: Mapped[int] = mapped_column(Integer, ForeignKey("houses.id"))
    status: Mapped[WarStatus] = mapped_column(
        ENUM(WarStatus, name="warstatus_enum", create_type=False),
        default=WarStatus.grace_period
    )
    is_civil_war: Mapped[bool] = mapped_column(Boolean, default=False)
    attacker_soldiers_lost: Mapped[int] = mapped_column(Integer, default=0)
    attacker_dragons_lost: Mapped[int] = mapped_column(Integer, default=0)
    attacker_scorpions_lost: Mapped[int] = mapped_column(Integer, default=0)
    defender_soldiers_lost: Mapped[int] = mapped_column(Integer, default=0)
    defender_dragons_lost: Mapped[int] = mapped_column(Integer, default=0)
    defender_scorpions_lost: Mapped[int] = mapped_column(Integer, default=0)
    gold_looted: Mapped[int] = mapped_column(BigInteger, default=0)
    winner_house_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("houses.id"), nullable=True
    )
    declared_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class WarAllySupport(Base):
    __tablename__ = "war_ally_supports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    war_id: Mapped[int] = mapped_column(Integer, ForeignKey("wars.id"))
    ally_house_id: Mapped[int] = mapped_column(Integer, ForeignKey("houses.id"))
    supported_house_id: Mapped[int] = mapped_column(Integer, ForeignKey("houses.id"))
    soldiers_sent: Mapped[int] = mapped_column(Integer, default=0)
    dragons_sent: Mapped[int] = mapped_column(Integer, default=0)
    scorpions_sent: Mapped[int] = mapped_column(Integer, default=0)
    is_full_support: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Alliance(Base):
    __tablename__ = "alliances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    house1_id: Mapped[int] = mapped_column(Integer, ForeignKey("houses.id"))
    house2_id: Mapped[int] = mapped_column(Integer, ForeignKey("houses.id"))
    status: Mapped[AllianceStatus] = mapped_column(
        ENUM(AllianceStatus, name="alliancestatus_enum", create_type=False),
        default=AllianceStatus.active
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    dissolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class HukmdorClaim(Base):
    __tablename__ = "hukmdor_claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    claimant_house_id: Mapped[int] = mapped_column(Integer, ForeignKey("houses.id"))
    region: Mapped[Region] = mapped_column(
        ENUM(Region, name="region_enum", create_type=False)
    )
    status: Mapped[ClaimStatus] = mapped_column(
        ENUM(ClaimStatus, name="claimstatus_enum", create_type=False),
        default=ClaimStatus.pending
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class HukmdorClaimResponse(Base):
    __tablename__ = "hukmdor_claim_responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    claim_id: Mapped[int] = mapped_column(Integer, ForeignKey("hukmdor_claims.id"))
    house_id: Mapped[int] = mapped_column(Integer, ForeignKey("houses.id"))
    accepted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class IronBankLoan(Base):
    __tablename__ = "iron_bank_loans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    house_id: Mapped[int] = mapped_column(Integer, ForeignKey("houses.id"))
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    interest_rate: Mapped[float] = mapped_column(Float, nullable=False)
    total_due: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[LoanStatus] = mapped_column(
        ENUM(LoanStatus, name="loanstatus_enum", create_type=False),
        default=LoanStatus.active
    )
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class MarketPrice(Base):
    __tablename__ = "market_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_type: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class BotSettings(Base):
    __tablename__ = "bot_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    value: Mapped[str] = mapped_column(String(500), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Chronicle(Base):
    __tablename__ = "chronicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    telegram_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class InternalMessage(Base):
    __tablename__ = "internal_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    house_id: Mapped[int] = mapped_column(Integer, ForeignKey("houses.id"))
    sender_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ── YANGI: Farm Schedule ───────────────────────────────────────────────────────

class FarmSchedule(Base):
    """
    Admin tomonidan belgilangan kunlik farm vaqtlari va miqdorlari.
    Har bir yozuv bitta farm vaqtini ifodalaydi.
    Masalan: 08:00 → 50 tanga, 14:30 → 100 tanga, 18:00 → 150 tanga
    """
    __tablename__ = "farm_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hour: Mapped[int] = mapped_column(Integer, nullable=False)    # 0–23
    minute: Mapped[int] = mapped_column(Integer, nullable=False)  # 0–59
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # tanga miqdori
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def time_str(self) -> str:
        """Vaqtni HH:MM formatida qaytaradi."""
        return f"{self.hour:02d}:{self.minute:02d}"

    def __repr__(self) -> str:
        status = "✅" if self.is_active else "❌"
        return f"<FarmSchedule {status} {self.time_str()} — {self.amount} tanga>"
