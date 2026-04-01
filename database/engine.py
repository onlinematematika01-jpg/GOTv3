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
    # Avval enum type larni yaratamiz (create_all dan oldin kerak)
    await _migrate_create_enums()

    # Jadvallarni yaratish
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_drop_region_unique(conn)

    # Ustun migratsiyalari — har biri alohida tranzaksiyada
    await _migrate_add_column(
        "wars", "war_type",
        "ALTER TABLE wars ADD COLUMN war_type wartypeenum NOT NULL DEFAULT 'external'"
    )
    await _migrate_add_column(
        "wars", "claim_id",
        "ALTER TABLE wars ADD COLUMN claim_id INTEGER REFERENCES hukmdor_claims(id) ON DELETE SET NULL"
    )
    await _migrate_add_column(
        "houses", "vassal_since",
        "ALTER TABLE houses ADD COLUMN vassal_since TIMESTAMP"
    )
    await _migrate_backfill_vassal_since()

    logger.info("Database jadvallari va migratsiyalar tayyor")
    await _seed_market_prices()
    await _seed_houses()


async def _migrate_create_enums():
    """Yangi PostgreSQL enum type larini yaratish"""
    async with engine.begin() as conn:
        try:
            await conn.execute(text(
                "CREATE TYPE wartypeenum AS ENUM ('external', 'civil')"
            ))
            logger.info("Migration: wartypeenum type yaratildi")
        except Exception:
            logger.info("Migration: wartypeenum allaqachon mavjud, o'tkazib yuborildi")


async def _migrate_add_column(table: str, column: str, sql: str):
    """Jadvalga ustun qo'shish — agar allaqachon bo'lsa o'tkazib yuboradi"""
    async with engine.begin() as conn:
        result = await conn.execute(text(
            f"SELECT 1 FROM information_schema.columns "
            f"WHERE table_name = '{table}' AND column_name = '{column}'"
        ))
        exists = result.scalar()
        if not exists:
            try:
                await conn.execute(text(sql))
                logger.info(f"Migration: {table}.{column} qo'shildi")
            except Exception as e:
                logger.warning(f"Migration xatosi ({table}.{column}): {e}")
        else:
            logger.info(f"Migration: {table}.{column} allaqachon mavjud")


async def _migrate_backfill_vassal_since():
    """
    Eski vassallar: is_under_occupation=True lekin vassal_since=NULL bo'lganlar.
    Ular isyon qila olishlari uchun vassal_since ni 3 kun oldin deb belgilaymiz
    (ya'ni ertaga o'lpon to'lab, keyin isyon ocha oladi).
    """
    async with engine.begin() as conn:
        result = await conn.execute(text(
            "SELECT COUNT(*) FROM houses "
            "WHERE is_under_occupation = TRUE AND vassal_since IS NULL"
        ))
        count = result.scalar()
        if count and count > 0:
            await conn.execute(text(
                "UPDATE houses SET vassal_since = NOW() - INTERVAL '3 days' "
                "WHERE is_under_occupation = TRUE AND vassal_since IS NULL"
            ))
            logger.info(f"Migration: {count} ta eski vassal xonadon vassal_since tuzatildi")
        else:
            logger.info("Migration: backfill kerak emas")


async def _migrate_drop_region_unique(conn):
    """houses.region dagi unique constraint ni olib tashlash"""
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
