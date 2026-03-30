from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text
from config.settings import settings
from database.models import Base
import logging

logger = logging.getLogger(__name__)

def _fix_db_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url

engine = create_async_engine(
    _fix_db_url(settings.DATABASE_URL),
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

AsyncSessionFactory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_drop_region_unique(conn)
    logger.info("Database jadvallari yaratildi")
    await _seed_market_prices()
    await _seed_houses()


async def _migrate_drop_region_unique(conn):
    """houses.region dagi unique constraint ni olib tashlash (bir martalik auto migration)"""
    try:
        await conn.execute(text("""
            DO $$
            DECLARE c TEXT;
            BEGIN
                SELECT constraint_name INTO c
                FROM information_schema.table_constraints
                WHERE table_name = 'houses'
                  AND constraint_type = 'UNIQUE'
                  AND constraint_name LIKE '%region%';
                IF c IS NOT NULL THEN
                    EXECUTE 'ALTER TABLE houses DROP CONSTRAINT ' || c;
                END IF;
            END $$;
        """))
        logger.info("Migration: houses.region unique constraint tekshirildi")
    except Exception as e:
        logger.warning(f"Migration xatosi (muhim emas): {e}")


async def _seed_market_prices():
    from database.models import MarketPrice
    from config.settings import settings as s
    async with AsyncSessionFactory() as session:
        from sqlalchemy import select
        result = await session.execute(select(MarketPrice))
        existing = result.scalars().all()
        if not existing:
            items = [
                MarketPrice(item_type="soldier", price=s.SOLDIER_PRICE),
                MarketPrice(item_type="dragon", price=s.DRAGON_PRICE),
                MarketPrice(item_type="scorpion", price=s.SCORPION_PRICE),
            ]
            session.add_all(items)
            await session.commit()
            logger.info("Bozor narxlari seed qilindi")


async def _seed_houses():
    from database.models import House, RegionEnum
    async with AsyncSessionFactory() as session:
        from sqlalchemy import select
        result = await session.execute(select(House))
        existing = result.scalars().all()
        if not existing:
            houses = [
                House(name="Stark xonadoni", region=RegionEnum.NORTH),
                House(name="Arryn xonadoni", region=RegionEnum.VALE),
                House(name="Tully xonadoni", region=RegionEnum.RIVERLANDS),
                House(name="Greyjoy xonadoni", region=RegionEnum.IRON_ISLANDS),
                House(name="Lannister xonadoni", region=RegionEnum.WESTERLANDS),
                House(name="Baratheon xonadoni", region=RegionEnum.KINGS_LANDING),
                House(name="Tyrell xonadoni", region=RegionEnum.REACH),
                House(name="Baratheon Firtinali xonadoni", region=RegionEnum.STORMLANDS),
                House(name="Martell xonadoni", region=RegionEnum.DORNE),
            ]
            session.add_all(houses)
            await session.commit()
            logger.info("9 ta xonadon seed qilindi")


async def get_session() -> AsyncSession:
    async with AsyncSessionFactory() as session:
        yield session
