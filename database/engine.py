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
    await _migrate_close_stale_claims()

    logger.info("Database jadvallari va migratsiyalar tayyor")
    await _seed_market_prices()
    await _seed_houses()
    await _migrate_create_alliance_group_tables()
    await _migrate_create_new_war_tables()
    await _migrate_create_stage1_tables()


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


async def _migrate_close_stale_claims():
    """
    Eski da'volar: barcha bog'liq urushlar tugagan lekin da'vo hali PENDING/IN_PROGRESS.
    Bunday da'volarni COMPLETED ga o'tkazamiz — yangi da'vo ochish imkoni berish uchun.
    """
    from sqlalchemy import update, and_, not_, exists, select
    from sqlalchemy.orm import Session
    from database.models import HukmdorClaim, War, ClaimStatusEnum, WarStatusEnum

    async with AsyncSessionFactory() as session:
        async with session.begin():
            # Tugagan urushga ega bo'lmagan pending/in_progress da'volarni topamiz
            war_subq = select(War.id).where(
                and_(
                    War.claim_id == HukmdorClaim.id,
                    War.status != WarStatusEnum.ENDED
                )
            ).correlate(HukmdorClaim)

            stmt = (
                update(HukmdorClaim)
                .where(
                    and_(
                        HukmdorClaim.status.in_([
                            ClaimStatusEnum.PENDING,
                            ClaimStatusEnum.IN_PROGRESS
                        ]),
                        not_(exists(war_subq))
                    )
                )
                .values(status=ClaimStatusEnum.COMPLETED)
            )
            result = await session.execute(stmt)
            count = result.rowcount

        if count:
            logger.info(f"Migration: {count} ta yetim da'vo COMPLETED qilindi")
        else:
            logger.info("Migration: yetim da'vo yo'q")


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


async def _migrate_create_alliance_group_tables():
    """Ittifoq guruhi jadvallarini yaratish (agar mavjud bo'lmasa)"""
    async with engine.begin() as conn:
        # alliance_groups
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS alliance_groups (
                id SERIAL PRIMARY KEY,
                name VARCHAR(64) NOT NULL,
                leader_house_id INTEGER NOT NULL REFERENCES houses(id),
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT NOW(),
                disbanded_at TIMESTAMP
            )
        """))
        # alliance_group_members
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS alliance_group_members (
                id SERIAL PRIMARY KEY,
                group_id INTEGER NOT NULL REFERENCES alliance_groups(id) ON DELETE CASCADE,
                house_id INTEGER NOT NULL REFERENCES houses(id),
                joined_at TIMESTAMP DEFAULT NOW()
            )
        """))
        # alliance_group_invites
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS alliance_group_invites (
                id SERIAL PRIMARY KEY,
                group_id INTEGER NOT NULL REFERENCES alliance_groups(id) ON DELETE CASCADE,
                from_house_id INTEGER NOT NULL REFERENCES houses(id),
                to_house_id INTEGER NOT NULL REFERENCES houses(id),
                status VARCHAR(16) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
    logger.info("Migration: ittifoq guruhi jadvallari tayyor")


async def _migrate_create_new_war_tables():
    """WarDeployment va Prisoner jadvallarini yaratish (agar mavjud bo'lmasa)"""

    # 1. prisonerstatusenum yaratish (xavfsiz — mavjud bo'lsa o'tkazib yuboradi)
    async with engine.begin() as conn:
        try:
            await conn.execute(text(
                "CREATE TYPE prisonerstatusenum AS ENUM ('captured', 'freed', 'executed')"
            ))
            logger.info("Migration: prisonerstatusenum type yaratildi")
        except Exception:
            logger.info("Migration: prisonerstatusenum allaqachon mavjud")

    # 2. war_deployments jadvali
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS war_deployments (
                id SERIAL PRIMARY KEY,
                war_id INTEGER NOT NULL REFERENCES wars(id) ON DELETE CASCADE,
                house_id INTEGER NOT NULL REFERENCES houses(id),
                soldiers INTEGER DEFAULT 0,
                dragons INTEGER DEFAULT 0,
                scorpions INTEGER DEFAULT 0,
                is_auto_defend BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP
            )
        """))

    # 3. prisoners jadvali
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS prisoners (
                id SERIAL PRIMARY KEY,
                prisoner_user_id BIGINT NOT NULL REFERENCES users(id),
                captor_house_id INTEGER NOT NULL REFERENCES houses(id),
                war_id INTEGER NOT NULL REFERENCES wars(id),
                ransom_amount BIGINT DEFAULT 0,
                status prisonerstatusenum DEFAULT 'captured',
                captured_at TIMESTAMP DEFAULT NOW(),
                freed_at TIMESTAMP
            )
        """))

    # 4. wars jadvaliga executed_lord_flag ustuni qo'shish
    await _migrate_add_column(
        "wars", "executed_lord_flag",
        "ALTER TABLE wars ADD COLUMN executed_lord_flag BOOLEAN DEFAULT FALSE"
    )

    logger.info("Migration: war_deployments, prisoners jadvallari va executed_lord_flag tayyor")


async def _migrate_create_stage1_tables():
    """
    BOSQICH 1 — HouseResources, TerritoryGarrison jadvallari va
    BotSettings kalit-qiymatlari (game_paused, pause_reason).
    Idempotent: allaqachon mavjud bo'lsa xatolik bermaydi.
    """

    # 1. house_resources jadvali
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS house_resources (
                id                SERIAL PRIMARY KEY,
                house_id          INTEGER NOT NULL UNIQUE REFERENCES houses(id) ON DELETE CASCADE,
                market_buy_limit  INTEGER NOT NULL DEFAULT 500,
                bank_min_loan     BIGINT  NOT NULL DEFAULT 100,
                bank_max_loan     BIGINT  NOT NULL DEFAULT 100000,
                daily_farm_amount INTEGER NOT NULL DEFAULT 50,
                updated_at        TIMESTAMP DEFAULT NOW()
            )
        """))
    logger.info("Migration (stage1): house_resources jadvali tayyor")

    # 2. territory_garrisons jadvali
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS territory_garrisons (
                id                SERIAL PRIMARY KEY,
                region            VARCHAR(64) NOT NULL UNIQUE,
                hukmdor_house_id  INTEGER NOT NULL REFERENCES houses(id) ON DELETE CASCADE,
                soldiers          INTEGER NOT NULL DEFAULT 0,
                dragons           INTEGER NOT NULL DEFAULT 0,
                scorpions         INTEGER NOT NULL DEFAULT 0,
                updated_at        TIMESTAMP DEFAULT NOW()
            )
        """))
    logger.info("Migration (stage1): territory_garrisons jadvali tayyor")

    # 3. BotSettings — game_paused va pause_reason kalitlari
    async with engine.begin() as conn:
        await conn.execute(text("""
            INSERT INTO bot_settings (key, value)
            VALUES ('game_paused', 'false')
            ON CONFLICT (key) DO NOTHING
        """))
        await conn.execute(text("""
            INSERT INTO bot_settings (key, value)
            VALUES ('pause_reason', '')
            ON CONFLICT (key) DO NOTHING
        """))
    logger.info("Migration (stage1): game_paused va pause_reason kalitlari tayyor")
