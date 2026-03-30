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
│   ├── chat.py               # Ichki xonadon chati
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
    └── scheduler.py          # Avtomatik vazifalar
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
| `soldiers` | Integer | Shaxsiy askarlar (lordning xaridlari) |
| `dragons` | Integer | Shaxsiy ajdarlar |
| `scorpions` | Integer | Shaxsiy skorpionlar |
| `debt` | BigInteger | Temir Bank qarzi |
| `is_exiled` | Boolean | Surgun holati |
| `referral_by` | FK → users | Kim taklif qilgan |
| `referral_count_today` | Integer | Bugungi referallar soni |
| `last_farm_date` | DateTime | Oxirgi farm sanasi |
| `is_active` | Boolean | Faollik holati |

> ⚠️ `user.gold` maydoni **olib tashlangan**. Barcha oltin faqat `house.treasury` da saqlanadi.

### `houses`
| Maydon | Tur | Izoh |
|--------|-----|------|
| `id` | Integer PK | |
| `name` | String | Xonadon nomi |
| `region` | Enum | Hudud |
| `lord_id` | FK → users | Lord |
| `high_lord_id` | FK → users | Hukmdor (Oliy Lord) |
| `treasury` | BigInteger | **Yagona oltin hisobi** |
| `total_soldiers` | Integer | Umumiy askarlar |
| `total_dragons` | Integer | Umumiy ajdarlar |
| `total_scorpions` | Integer | Umumiy skorpionlar |
| `is_under_occupation` | Boolean | Bosib olinganmi |
| `occupier_house_id` | FK → houses | Bosib olgan xonadon |
| `permanent_tax_rate` | Float | Doimiy soliq (taslim bo'lganda) |

### Boshqa Jadvallar
- `wars` — Urush yozuvlari (attacker, defender, status, yo'qotmalar, o'lja)
- `war_ally_supports` — Ittifoqchi yordamlari
- `alliances` — Faol ittifoqlar
- `hukmdor_claims` — Hukmdorlik da'volari
- `hukmdor_claim_responses` — Xonadonlarning da'voga javoblari
- `iron_bank_loans` — Qarz yozuvlari
- `market_prices` — Bozor narxlari (DB da, admin o'zgartiradi)
- `bot_settings` — Bank foiz, limit sozlamalari
- `chronicles` — Tarix yozuvlari
- `internal_messages` — Xonadon ichki chat

---

## 💰 Iqtisod Tizimi

### Yagona Xazina Prinsipi
Barcha oltin **faqat xonadon xazinasida** (`house.treasury`) saqlanadi. Hech bir foydalanuvchining shaxsiy oltini yo'q.

### Pul Kirimi
| Manba | Miqdor | Qayerga |
|-------|--------|---------|
| Kunlik farm (A'zo) | +20 tanga/kun | Xonadon xazinasiga |
| Kunlik farm (Lord/High Lord) | +50 tanga/kun | Xonadon xazinasiga |
| Referral bonus | +50 tanga | Taklif qiluvchining **xonadon xazinasiga** |
| O'lpon (vassal → hukmdor) | 100 × a'zolar soni/kun | Hukmdor xonadoniga |
| Urush o'ljasi | Raqib xazinasining 51% | G'olib xonadon xazinasiga |
| Admin sovg'a | Belgilangan miqdor | Xonadon xazinasiga |

### Pul Sarfi
| Sabab | Miqdor | Kimdan |
|-------|--------|--------|
| Bozor xaridi | Narx × miqdor | Xonadon xazinasidan |
| Qarz to'lash | Qarz miqdori | Xonadon xazinasidan |
| O'lpon (vassal) | 100 × a'zolar soni/kun | Vassal xonadon xazinasidan |

### Cheklovlar
- **Faqat Lord yoki High Lord** bozordan xarid qila oladi
- **Faqat Lord yoki High Lord** bank qarzini ola/to'lay oladi
- Qarz **xonadon xazinasiga** tushadi, **xazinadan** to'lanadi

---

## ⚔️ Urush Tizimi

### Vaqt Oynasi
| Harakat | Vaqt (O'zbekiston, UTC+5) |
|---------|--------------------------|
| Urush e'lon qilish | 19:00 — 22:00 |
| Jang davri | 19:00 — 23:00 |
| Avtomatik yakunlash | 23:00 |

### Urush Bosqichlari
1. **Grace Period** (60 daqiqa) — mudofaachi taslim yoki jang tanlab oladi
2. **Fighting** — jang davom etadi
3. **Ended** — 23:00 da avtomatik hisoblanadi

### Jang Mexanikasi (3-Round)
| Round | Kimlar | Hal qiluvchi |
|-------|--------|-------------|
| 1-Round | Ajdar ↔ Skorpion | Ko'proq ajdar yo'q qilgan |
| 2-Round | Ajdar ↔ Askar | Kuch nisbati |
| 3-Round | Askar ↔ Askar | **G'olibni hal qiladi** |

> **Eslatma:** 3-Round natijasi yagona g'olibni belgilaydi (1-2-round faqat resurs kamaytiradi).

### O'lja
- G'olib: raqib **xazinasining 51%** + **qo'shinlarining 51%**
- Taslim bo'lish: **50%** resurslar tinch yo'l bilan o'tadi + 10% doimiy soliq

### Civil Urush (Hukmdorlik Da'vosi)
1. Lord → "👑 Hukmdorlik Da'vosi" bosadi
2. Hududdagi boshqa xonadon lordlarga xabar ketadi (1 soat muddat)
3. Qabul → Vassal bo'ladi | Rad → Civil urush boshlanadi
4. Barcha urushlar tugagach — g'olib **High Lord** bo'ladi

---

## 🤝 Ittifoq Tizimi
- Faqat Lord/High Lord ittifoq tuza oladi
- Ittifoqchi urushda 2 xil yordam beradi:
  - **To'liq qo'shilish** — barcha resurs bilan jangga kiradi
  - **Askar yuborish** — belgilangan miqdor askar yuboradi
- **Hukmdor urush ochsa → barcha ittifoqlari avtomatik buziladi**

---

## 🏦 Temir Bank
- Faqat Lord qarz ola/to'lay oladi
- Qarz **xonadon xazinasiga** tushadi
- To'lash **xonadon xazinasidan** amalga oshiriladi
- Muddat o'tsa → xonadon qo'shinlari va ajdarlari musodara qilinadi
- Foiz stavkasi va limitlar admin tomonidan DB da sozlanadi

---

## 🔧 Scheduler Vazifalari
| Vazifa | Vaqt | Nima qiladi |
|--------|------|-------------|
| `daily_farm_job` | 08:00 UTC | Har a'zo farm summasini xonadon xazinasiga qo'shadi, o'lpon o'tkazadi |
| `check_grace_period_job` | Har 5 daqiqa | Grace Period tugagan urushlarni FIGHTING ga o'tkazadi |
| `end_war_time_job` | 23:00 UTC | Barcha faol urushlarni hisoblab yakunlaydi |
| `check_iron_bank_debt_job` | 00:00 UTC | Muddati o'tgan qarzlar uchun musodara qiladi |
| `check_civil_wars_job` | Har 10 daqiqa | Civil urushlar tugashini tekshirib Hukmdor belgilaydi |
| `check_claim_timeouts_job` | Har 15 daqiqa | 1 soat javob bermagan xonadonlarni rad etilgan deb belgilaydi |

---

## 👥 Rol Tizimi
| Rol | Telegram Nomi | Huquqlar |
|-----|---------------|----------|
| `admin` | 🦅 Uch Ko'zli Qarg'a | Hamma narsa |
| `high_lord` | 👑 Hukmdor | Urush, bozor, bank, da'vo, diplomatiya |
| `lord` | 🏰 Vassal Lordi | Urush, bozor, bank, da'vo, diplomatiya |
| `member` | ⚔️ A'zo | Faqat ko'rish, ichki chat, xiyonat |

---

## ⚠️ Mavjud Kamchiliklar (To Do)

### Kritik
- **Referral havolasi yo'q** — foydalanuvchiga o'z referral linkini ko'rsatuvchi tugma/buyruq yo'q. `profile.py` da tugma qo'shish kerak.
- **`profile.py` yarim yozilgan** — oxirgi tahrirlash to'liq tugallanmagan, fayl sintaksis xatosi bilan tugaydi.
- **DB Migration** — `users.gold` ustuni olib tashlangan, ammo bazada hali mavjud. Migratsiya kerak:
  ```sql
  ALTER TABLE users DROP COLUMN gold;
  ```

### O'rta Darajali
- **Xiyonat tugmasi yo'q** — `war.py` da `🗡️ Xiyonat` text handler bor, lekin menyu tugmasi yo'q.
- **Bozor: a'zolar qo'shini** — A'zo xarid qilolmaydi, lekin `user.soldiers` maydoni bor; ular urushda hisob-kitobga kirmaydi (faqat xonadon `total_soldiers` ishlatiladi). Bu chalkashlikka sabab bo'ladi.
- **`referral_count_today` schedulerda nollanadi**, lekin qo'shib qo'yish mexanikasi yo'q — faqat `get_referral_count_today()` DB dan hisoblaydi, xato bo'lishi mumkin.
- **O'lpon (tribute) schedulerda ikki marta hisoblanishi mumkin** — `update_treasury` commit ichida chaqiriladi, keyin yana scheduler loop davom etadi.

### Kichik
- **`bank.py` da duplikat kod** — eski versiyada `BankState` va handlerlar ikki marta yozilgan edi (yangi versiyada tuzatildi).
- **`war_ally.py` ittifoqchi yordami** xonadon `total_soldiers` ga qo'shilmaydi, faqat jang paytida hisoblanadi — bu to'g'ri, lekin profilda ko'rinmaydi.
- **Admin panel** — `give_gold` funksiyasi endi `house_id` talab qiladi, lekin xatolik holatida `HouseRepo` importi `admin.py` da local qilingan.

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

DEFAULT_INTEREST_RATE=0.10
```

---

## 🚀 Ishga Tushirish
```bash
pip install -r requirements.txt
# .env faylini to'ldiring
# DB migratsiyasini bajaring (agar mavjud DB bo'lsa):
# ALTER TABLE users DROP COLUMN IF EXISTS gold;
python main.py
```
