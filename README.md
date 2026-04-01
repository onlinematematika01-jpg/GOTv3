# 🐺 Game of Thrones Bot V3 — Loyiha Holati

## 📦 Texnik Stack
- **Python 3.11+**
- **Aiogram 3.x** — Telegram Bot framework
- **SQLAlchemy (async)** + **PostgreSQL** — Ma'lumotlar bazasi
- **APScheduler** — Kunlik vazifalar (farm, urush tugashi, bank tekshiruvi)
- **Pydantic Settings** — `.env` orqali konfiguratsiya

---

## 🗂️ Loyiha Tuzilmasi

```
GOTv3/
├── main.py                   # Bot ishga tushirish, scheduler
├── config/
│   └── settings.py           # .env sozlamalari
├── database/
│   ├── engine.py             # Async PostgreSQL ulanish
│   ├── models.py             # SQLAlchemy modellari
│   └── repositories.py       # DB so'rovlari (Repository pattern)
├── handlers/
│   ├── start.py              # /start, /help
│   ├── profile.py            # Profil, xonadon ko'rinishi
│   ├── market.py             # Bozor (askar/ajdar/skorpion)
│   ├── bank.py               # Temir Bank (qarz/to'lash)
│   ├── war.py                # Urush e'lon qilish, taslim bo'lish
│   ├── war_ally.py           # Ittifoqchi yordam mexanikasi
│   ├── diplomacy.py          # Ittifoq tuzish/buzish
│   ├── claim.py              # Hukmdorlik da'vosi
│   ├── rating.py             # Reyting
│   ├── chat.py               # Ichki xonadon chati (Toshkent vaqti)
│   ├── chronicle.py          # Xronika ko'rinishi
│   └── admin.py              # Admin panel
├── keyboards/
│   └── keyboards.py          # Barcha klaviaturalar
├── middlewares/
│   ├── auth.py               # Foydalanuvchi autentifikatsiya
│   └── logging.py            # So'rovlarni loglash
└── utils/
    ├── battle.py             # Jang hisob-kitobi (3-roundlik)
    ├── chronicle.py          # Telegram kanalga xronika post
    ├── scheduler.py          # Avtomatik vazifalar
    └── time_utils.py         # Toshkent vaqt konversiyalari (UTC+5)
```

---

## 🗄️ Ma'lumotlar Bazasi Modellari

### `users`
| Maydon | Tur | Izoh |
|--------|-----|------|
| `id` | BigInteger PK | Telegram user ID |
| `username` | String | Telegram username |
| `full_name` | String | To'liq ism |
| `role` | Enum | admin / high_lord / lord / member |
| `region` | Enum | 9 ta hudud |
| `house_id` | FK → houses | Xonadoni |
| `soldiers` | Integer | Shaxsiy askarlar |
| `dragons` | Integer | Shaxsiy ajdarlar |
| `scorpions` | Integer | Shaxsiy skorpionlar |
| `debt` | BigInteger | Temir Bank qarzi (shaxsiy kuzatuv) |
| `is_exiled` | Boolean | Surgun holati |
| `referral_by` | FK → users | Kim taklif qilgan |
| `referral_count_today` | Integer | Bugungi referallar soni |
| `is_active` | Boolean | Faollik holati |

### `houses`
| Maydon | Tur | Izoh |
|--------|-----|------|
| `id` | Integer PK | |
| `name` | String | Xonadon nomi |
| `region` | Enum | Hudud |
| `lord_id` | FK → users | Lord |
| `high_lord_id` | FK → users | Hukmdor (Oliy Lord) |
| `treasury` | BigInteger | **Yagona oltin hisobi** |
| `total_soldiers` | Integer | Umumiy askarlar (manfiy bo'lmaydi) |
| `total_dragons` | Integer | Umumiy ajdarlar (manfiy bo'lmaydi) |
| `total_scorpions` | Integer | Umumiy skorpionlar (manfiy bo'lmaydi) |
| `is_under_occupation` | Boolean | Bosib olinganmi |
| `occupier_house_id` | FK → houses | Bosib olgan xonadon |
| `permanent_tax_rate` | Float | Doimiy soliq (taslim bo'lganda) |

### `iron_bank_loans`
| Maydon | Tur | Izoh |
|--------|-----|------|
| `id` | Integer PK | |
| `user_id` | FK → users | Qarz olgan lord |
| `house_id` | FK → houses | Qarz olgan xonadon |
| `principal` | BigInteger | Asosiy qarz miqdori |
| `interest_rate` | Float | Foiz stavkasi |
| `total_due` | BigInteger | Foiz bilan jami |
| `paid` | Boolean | To'langanmi |
| `due_date` | DateTime | To'lash muddati |

### `war_ally_supports`
| Maydon | Tur | Izoh |
|--------|-----|------|
| `war_id` | FK → wars | |
| `ally_house_id` | FK → houses | Yordam beruvchi xonadon |
| `side` | String | `attacker` / `defender` |
| `join_type` | String | `full` / `soldiers` / `gold` |
| `soldiers` | Integer | Yuborilgan askarlar |
| `dragons` | Integer | Har doim 0 (ajdar yuborib bo'lmaydi) |
| `scorpions` | Integer | Yuborilgan skorpionlar |
| `gold` | BigInteger | Yuborilgan oltin (darhol o'tkaziladi) |

### Boshqa Jadvallar
- `wars` — Urush yozuvlari (`war_type` String: `EXTERNAL` / `CIVIL`)
- `alliances` — Faol ittifoqlar
- `hukmdor_claims` — Hukmdorlik da'volari
- `market_prices` — Bozor narxlari
- `bot_settings` — Bank foiz, limit, farm jadvali (JSON)
- `chronicles` — Tarix yozuvlari
- `internal_messages` — Xonadon ichki chat

---

## 💰 Iqtisod Tizimi

### Yagona Xazina Prinsipi
Barcha oltin **faqat xonadon xazinasida** (`house.treasury`) saqlanadi.

### Pul Kirimi
| Manba | Miqdor | Qayerga |
|-------|--------|---------|
| Kunlik farm (A'zo) | +20 tanga/kun | Xonadon xazinasiga |
| Kunlik farm (Lord/High Lord) | +50 tanga/kun | Xonadon xazinasiga |
| Referral bonus | +50 tanga | Taklif qiluvchining xonadon xazinasiga |
| O'lpon (vassal → hukmdor) | 100 × a'zolar soni/kun | Hukmdor xonadoniga |
| Urush o'ljasi | Raqib xazinasining 51% | G'olib xonadon xazinasiga |

### Cheklovlar
- **Faqat Lord yoki High Lord** bozordan xarid qila oladi
- **Faqat Lord yoki High Lord** bank qarzini ola/to'lay oladi
- Qarz tekshiruvi **xonadon darajasida** — lord almashsa ham yangi lord qarz ustiga qarz ololmaydi
- Askarlar, ajdarlar, skorpionlar **manfiy bo'lmaydi** (`GREATEST(..., 0)`)

---

## ⚔️ Urush Tizimi

### Vaqt Oynasi (Toshkent, UTC+5)
| Harakat | Vaqt |
|---------|------|
| Urush e'lon qilish | **19:00 — 22:00** (22:01 dan bloklangan) |
| Grace period | E'lon qilingan paytdan **1 soat** |
| Jang boshlanishi | Grace tugagan zahoti (**darhol**, 5 daqiqada tekshiriladi) |
| Zaxira yakunlash | 23:00 (qolgan urushlar uchun) |

> **Qoida:** 22:01 dan keyin urush e'lon qilib bo'lmaydi — mudofaachiga kamida 1 soat kafolatlanadi.

### Urush Bosqichlari
1. **Grace Period** (60 daqiqa) — mudofaachi taslim yoki jang tanlab oladi
2. Grace tugashi → **darhol jang**, roundlar alohida xabar sifatida yuboriladi
3. **Ended** — natijalar va xronika

### Jang Mexanikasi (3-Round)
| Round | Kimlar | Natija |
|-------|--------|--------|
| 1-Round | Ajdar ↔ Skorpion | Ko'proq ajdar yo'q qilgan yutadi |
| 2-Round | Ajdar ↔ Askar | Kuch nisbati |
| 3-Round | Askar ↔ Askar | **G'olibni hal qiladi** |

Har bir round **alohida xabar** sifatida lordlarga yuboriladi.

### O'lja
- G'olib: raqib **xazinasining 51%** + **qo'shinlarining 51%**
- Taslim bo'lish: **50%** resurslar + 10% doimiy soliq

### Ittifoqchi Yordam
Urush e'lon qilingan zahoti **hujumchi ham, mudofaachi ham** ittifoqchilariga avtomatik xabar ketadi.

| Yordam turi | Nima yuboriladi | Ajdar |
|-------------|-----------------|-------|
| ⚔️ To'liq qo'shilish | Barcha askar + skorpion | ❌ Yuborilmaydi |
| 🗡️ Askar yuborish | Tanlangan miqdor askar | ❌ |
| 💰 Oltin yuborish | Tanlangan miqdor (darhol o'tkaziladi) | ❌ |

> **Ittifoq buzilishi:** C xonadon B ga yordam bersa, A bilan ittifoqi avtomatik bekor bo'ladi.

### Civil Urush
1. Lord → "👑 Hukmdorlik Da'vosi"
2. Hududdagi xonadonlarga xabar (1 soat muddat)
3. Qabul → Vassal | Rad/Javob bermasa → Civil urush
4. Barcha urushlar tugagach g'olib **High Lord** bo'ladi

---

## 🏦 Temir Bank

- Faqat Lord qarz ola/to'lay oladi
- **Xonadon darajasida** tekshiriladi — lord almashsa ham qarz xonadonga bog'liq
- Qarz xonadon xazinasiga tushadi, xazinadan to'lanadi
- Muddat o'tsa → qo'shin va ajdarlar musodara

### Admin Qarzdorlar Paneli (`💸 Qarzdorlar`)
| Amal | Tavsif |
|------|--------|
| 📅 Muddatni uzaytirish | Necha kun kiritiladi, lordga xabar |
| ⚔️ Resurs musodara | `askar:500 ajdar:2 skorpion:10 oltin:1000` formatida |
| 🎁 Qarzni kechirish | To'liq qarz o'chiriladi |

---

## 🔧 Scheduler Vazifalari (Toshkent vaqti)
| Vazifa | Vaqt | Nima qiladi |
|--------|------|-------------|
| `daily_farm_job` | Admin belgilagan vaqt | Farm summasi + barcha a'zolarga xabar |
| `check_grace_period_job` | Har 5 daqiqa | Grace tugagan urushlarni **darhol** hisoblaydi |
| `end_war_time_job` | 23:00 | Qolgan urushlarni zaxira sifatida yakunlaydi |
| `check_iron_bank_debt_job` | 00:00 | Muddati o'tgan qarzlar musodara |
| `check_civil_wars_job` | Har 10 daqiqa | Civil urushlar + Hukmdor belgilash |
| `check_claim_timeouts_job` | Har 15 daqiqa | Javob bermagan xonadonlarni rad etish |

> Barcha `CronTrigger` da `timezone="Asia/Tashkent"` ishlatiladi.

---

## 👥 Rol Tizimi
| Rol | Nomi | Huquqlar |
|-----|------|----------|
| `admin` | 🦅 Uch Ko'zli Qarg'a | Hamma narsa |
| `high_lord` | 👑 Hukmdor | Urush, bozor, bank, da'vo, diplomatiya |
| `lord` | 🏰 Vassal Lordi | Urush, bozor, bank, da'vo, diplomatiya |
| `member` | ⚔️ A'zo | Ko'rish, ichki chat, urushda xiyonat |

---

## 🗃️ Muhim Migratsiyalar

```sql
-- 1. Ittifoqchi oltin yuborish uchun
ALTER TABLE war_ally_supports ADD COLUMN gold BIGINT DEFAULT 0;

-- 2. Qarzni xonadonga bog'lash uchun
ALTER TABLE iron_bank_loans ADD COLUMN house_id INTEGER REFERENCES houses(id);
UPDATE iron_bank_loans l SET house_id = (SELECT house_id FROM users WHERE id = l.user_id);

-- 3. Manfiy resurslarni tuzatish
UPDATE houses SET total_soldiers = 0 WHERE total_soldiers < 0;
UPDATE houses SET total_dragons = 0 WHERE total_dragons < 0;
UPDATE houses SET total_scorpions = 0 WHERE total_scorpions < 0;

-- 4. To'langan lekin paid=False qolgan eski qarzlarni tozalash
UPDATE iron_bank_loans l SET paid = TRUE
WHERE l.paid = FALSE
AND (SELECT debt FROM users WHERE id = l.user_id) = 0;
```

---

## 🔧 .env Namunasi
```env
BOT_TOKEN=your_bot_token_here
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/got_bot
CHRONICLE_CHANNEL_ID=-100xxxxxxxxx
ADMIN_IDS=[123456789]

WAR_START_HOUR=19
WAR_END_HOUR=23
WAR_DECLARE_DEADLINE=22
GRACE_PERIOD_MINUTES=60

LORD_DAILY_INCOME=50
MEMBER_DAILY_INCOME=20
VASSAL_DAILY_TRIBUTE=100
REFERRAL_BONUS=50
MAX_REFERRAL_PER_DAY=10

SOLDIER_PRICE=1
DRAGON_PRICE=150
SCORPION_PRICE=25
SCORPIONS_PER_DRAGON=3
DRAGON_KILLS_SOLDIERS=200
WAR_LOOT_PERCENT=0.51
SURRENDER_LOOT_PERCENT=0.50
MAX_HOUSE_MEMBERS=10

DEFAULT_INTEREST_RATE=0.10
```

---

## 🚀 Ishga Tushirish
```bash
pip install -r requirements.txt
# .env faylini to'ldiring
# Migratsiyalarni bajaring (yuqoridagi SQL lar)
python main.py
```
