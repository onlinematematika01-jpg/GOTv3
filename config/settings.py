from pydantic_settings import BaseSettings
from typing import Optional, List


class Settings(BaseSettings):
    BOT_TOKEN: str = "YOUR_BOT_TOKEN"
    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost:5432/got_bot"
    CHRONICLE_CHANNEL_ID: Optional[int] = None
    BANK_MARKET_CHANNEL_ID: Optional[int] = None   # Temir bank va bozor xabarlari kanali
    REQUIRED_CHANNEL_ID: Optional[int] = None   # Majburiy obuna kanali (masalan: -1001234567890)
    REQUIRED_CHANNEL_LINK: Optional[str] = None  # Kanal havolasi (masalan: https://t.me/kanalim)
    ADMIN_IDS: List[int] = []

    # O'yin sozlamalari
    WAR_START_HOUR: int = 19
    WAR_END_HOUR: int = 23
    WAR_DECLARE_DEADLINE: int = 22
    GRACE_PERIOD_MINUTES: int = 60

    # Narxlar
    SOLDIER_PRICE: int = 1
    DRAGON_PRICE: int = 150
    SCORPION_PRICE: int = 25

    # Daromadlar
    LORD_DAILY_INCOME: int = 50
    MEMBER_DAILY_INCOME: int = 20
    VASSAL_DAILY_TRIBUTE: int = 100
    REFERRAL_BONUS: int = 50
    MAX_REFERRAL_PER_DAY: int = 10

    # Urush
    SCORPIONS_PER_DRAGON: int = 3
    DRAGON_KILLS_SOLDIERS: int = 200
    WAR_LOOT_PERCENT: float = 0.51
    SURRENDER_LOOT_PERCENT: float = 0.50
    MAX_HOUSE_MEMBERS: int = 10

    # Ritsar
    KNIGHT_MAX_SOLDIERS: int = 100      # Ritsarning maksimal shaxsiy askari
    KNIGHT_DAILY_FARM: int = 10          # Ritsarning kunlik farm
    KNIGHT_SOLDIER_BUY_LIMIT: int = 50   # Bir marta xarid limiti

    # Iron Bank
    DEFAULT_INTEREST_RATE: float = 0.10

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
