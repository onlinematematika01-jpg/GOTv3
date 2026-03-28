# 🐺 Game of Thrones Bot V3

Ko'p foydalanuvchili strategik simulyator — 9 hudud, dinamik ierarxiya, iqtisodiy tizim va urush mexanikasi.

## 📁 Loyiha Tuzilishi

```
got_bot/
├── main.py                  # Bot ishga tushirish nuqtasi
├── requirements.txt
├── .env.example
├── config/
│   └── settings.py          # Barcha sozlamalar (pydantic-settings)
├── database/
│   ├── models.py            # SQLAlchemy ORM modellari
│   ├── engine.py            # Asinxron engine, sessiya, seed
│   └── repositories.py      # CRUD — UserRepo, HouseRepo, WarRepo...
├── handlers/
│   ├── start.py             # /start, /help, ro'yxatdan o'tish
│   ├── profile.py           # 👤 Profil, 🏰 Xonadon
│   ├── market.py            # 🛒 Bozor — askar/ajdar/skorpion
│   ├── war.py               # ⚔️ Urush — e'lon, taslim, jang, xiyonat
│   ├── bank.py              # 🏦 Temir Bank — qarz/to'lash
│   ├── diplomacy.py         # 🤝 Ittifoq tuzish/buzish
│   ├── chat.py              # 💬 Xonadon ichki chat
│   ├── admin.py             # 🔧 Admin panel
│   └── chronicle.py         # 📜 Xronika ko'rish
├── keyboards/
│   └── keyboards.py         # Inline va Reply klaviaturalar
├── middlewares/
│   ├── auth.py              # Foydalanuvchi tekshiruvi
│   └── logging.py           # Loglar
└── utils/
    ├── battle.py            # Jang formulasi (Air + Ground Phase)
    ├── chronicle.py         # Telegram kanalga post qilish
    └── scheduler.py         # APScheduler — kunlik farm, urush taymer
```

## ⚙️ O'rnatish

```bash
# 1. Muhit yaratish
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 2. Kutubxonalar
pip install -r requirements.txt

# 3. .env fayl
cp .env.example .env
# .env ni tahrirlang: BOT_TOKEN, DATABASE_URL, CHRONICLE_CHANNEL_ID

# 4. PostgreSQL bazasini yaratish
createdb got_bot

# 5. Botni ishga tushirish
python main.py
```

## 🗺️ 9 ta Hudud va Xonadonlar

| Hudud | Xonadon |
|-------|---------|
| Shimol | Stark xonadoni |
| Vodiy | Arryn xonadoni |
| Daryo yerlari | Tully xonadoni |
| Temir orollar | Greyjoy xonadoni |
| G'arbiy yerlar | Lannister xonadoni |
| Qirollik bandargohi | Baratheon xonadoni |
| Tyrellar vodiysi | Tyrell xonadoni |
| Bo'ronli yerlar | Baratheon Fırtınalı xonadoni |
| Dorn | Martell xonadoni |

## 👑 Rollar

- **Admin (Uch Ko'zli Qarg'a)** — `ADMIN_IDS` ro'yxatiga qo'shiladi
- **Oliy Lord (Hukmdor)** — DB da `high_lord_id` orqali belgilanadi
- **Vassal Lordi** — `/start` da bo'sh xonadonga avtomatik tayinlanadi
- **A'zo** — to'lgan xonadonlarga qo'shiladi

## ⚔️ Urush Vaqti

`.env` da UTC soat bilan belgilang:
```
WAR_START_HOUR=14    # O'zbekiston 19:00 = UTC 14:00
WAR_END_HOUR=18      # O'zbekiston 23:00 = UTC 18:00
WAR_DECLARE_DEADLINE=17
```

## 🏦 Temir Bank

Admin `/admin` → "Bank Foiz O'zgartirish" orqali foizni o'zgartiradi.
Qarz 7 kun ichida to'lanmasa — barcha qo'shin va ajdarlar musodara qilinadi.

## 📢 Xronika Kanali

`CHRONICLE_CHANNEL_ID` ga Telegram kanal ID sini qo'ying.
Bot kaналга admin sifatida qo'shilishi kerak.

## 🔧 Admin Buyruqlar

- `/admin` — Admin panel
- `/give_gold <user_id> <miqdor>` — Foydalanuvchiga oltin berish
