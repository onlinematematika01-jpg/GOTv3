# Alembic migratsiyalarini ishlatish uchun

# 1. Alembic ni ishga tushirish:
#    alembic init alembic

# 2. alembic/env.py ga qo'shing:
#    from database.models import Base
#    target_metadata = Base.metadata

# 3. Birinchi migratsiya:
#    alembic revision --autogenerate -m "initial"

# 4. Migratsiyani qo'llash:
#    alembic upgrade head

# alembic.ini ga DATABASE_URL qo'shing:
# sqlalchemy.url = postgresql+psycopg2://user:pass@localhost/got_bot

# Yoki to'g'ridan async engine bilan ishlash uchun
# database/engine.py da create_tables() funksiyasidan foydalaning.
