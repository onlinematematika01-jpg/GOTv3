from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from keyboards.keyboards import guide_keyboard

router = Router()

GUIDE_TEXT = {
    "main": (
        "📖 <b>O'YIN QO'LLANMASI</b>\n\n"
        "Quyidagi bo'limlardan birini tanlang:\n\n"
        "⚔️ <b>Urush</b> — e'lon qilish, bosqichlar, taslim bo'lish\n"
        "🐉 <b>Jang mexanikasi</b> — 3 round tizimi, resurslar\n"
        "🤝 <b>Diplomatiya</b> — ittifoqlar, yordam turlari\n"
        "🛒 <b>Bozor</b> — resurslar va custom qurollar\n"
        "⛓️ <b>Asirlar</b> — asirlik qoidalari\n"
        "👑 <b>Rollar</b> — vakolatlar va unvonlar"
    ),

    "urush": (
        "⚔️ <b>URUSH QO'LLANMASI</b>\n\n"
        "<b>E'lon qilish shartlari:</b>\n"
        "• Faqat belgilangan vaqt oralig'ida\n"
        "• Kamida bitta resurs (askar/ajdar/skorpion) bo'lishi shart\n"
        "• Asirlikda urush e'lon qilib bo'lmaydi\n"
        "• Lord — faqat o'z hududi xonadoniga\n"
        "• High Lord — barcha hududlarga\n"
        "• Ittifoq a'zosiga urush qilib bo'lmaydi\n\n"
        "<b>Bosqichlar:</b>\n"
        "1️⃣ Urush e'lon → Grace period boshlanadi\n"
        "2️⃣ Resurs yuborish (Deployment)\n"
        "3️⃣ Urush vaqti tugaganda — avtomatik hisoblash\n\n"
        "<b>Taslim bo'lish oqibatlari:</b>\n"
        "• Xazinaning 50% yo'qoladi\n"
        "• Askar va ajdarlarning 50% yo'qoladi\n"
        "• Custom itemlardan 51% o'tadi\n"
        "• 10% doimiy soliq belgilanadi\n"
        "• Agar High Lord bo'lsa — unvon g'olibga o'tadi"
    ),

    "jang": (
        "🐉 <b>JANG MEXANIKASI</b>\n\n"
        "<b>3 round tizimi — 3-round natijasi hal qiladi:</b>\n\n"
        "🔥 <b>1-Round: Ajdar vs Skorpion</b>\n"
        "Skorpionlar ajdarlarni o'ldiradi.\n"
        "N ta skorpion = 1 ta ajdar.\n"
        "DEFENSE custom itemlar ham skorpion kabi ishlaydi.\n\n"
        "🐉 <b>2-Round: Ajdar vs Askar</b>\n"
        "Har bir ajdar 20 askarni o'ldiradi.\n"
        "ATTACK itemlar ajdar kabi, SOLDIER itemlar askar kabi ishlaydi.\n\n"
        "⚔️ <b>3-Round: Askar vs Askar</b>\n"
        "Askar ko'p tomon g'alaba qozonadi — BU ROUND HAL QILADI.\n\n"
        "<b>Qal'a mudofaasi:</b>\n"
        "Agar mudofaa balli > hujumchi ajdarlari → barcha hujumchi resurslari yarimlandi!\n\n"
        "<b>G'olib o'ljasi:</b>\n"
        "Mudofaachi xazinasi, askar, ajdar va custom itemlarining 51%"
    ),

    "diplo": (
        "🤝 <b>DIPLOMATIYA QO'LLANMASI</b>\n\n"
        "<b>Ittifoq guruhi qoidalari:</b>\n"
        "• 2 dan 3 tagacha xonadon birlashadi\n"
        "• Faqat bir hududdagi xonadonlar ittifoq tuza oladi\n"
        "• Bir xonadon faqat bitta guruhda bo'la oladi\n"
        "• Faqat Lord va High Lord diplomatiya olib boradi\n\n"
        "<b>Yordam turlari:</b>\n"
        "🗡️ <b>To'liq qo'shilish (full)</b> — barcha resurslar bilan jangga kiradi\n"
        "👥 <b>Askar yuborish (soldiers)</b> — faqat askarlar yuboriladi\n\n"
        "<b>Diqqat:</b>\n"
        "Ittifoqchi xonadonga yangi urush e'lon qilinsa — o'sha tomon bergan yordam avtomatik bekor qilinadi!\n\n"
        "<b>High Lord:</b>\n"
        "Hududning hukmdori. Barcha hududlarga urush e'lon qila oladi. "
        "Mag'lub bo'lsa — unvon g'olibga o'tadi."
    ),

    "bozor": (
        "🛒 <b>BOZOR QO'LLANMASI</b>\n\n"
        "<b>Standart resurslar:</b>\n"
        "🗡️ Askar — eng arzon. 3-roundda ishlaydi.\n"
        "🐉 Ajdar — eng qimmat. 1 va 2-roundda kuchli.\n"
        "🏹 Skorpion — ajdarga qarshi. 1-roundda ishlaydi.\n\n"
        "<b>Custom (maxsus) qurol turlari:</b>\n"
        "⚔️ <b>ATTACK</b> — 1 item = N askarni yo'q qiladi (ajdar kabi). "
        "Uni o'ldirish uchun N+1 askar kerak.\n\n"
        "🛡️ <b>DEFENSE</b> — 1 item = M ta skorpion ekvivalenti (1-roundda). "
        "defense_power=0 bo'lsa skorpionlar ta'sir qila olmaydi.\n\n"
        "👥 <b>SOLDIER</b> — 1 item = N ta qo'shimcha askar (2 va 3-roundda).\n\n"
        "⚠️ Faqat xonadon lordi xazinadan xarid qila oladi."
    ),

    "asir": (
        "⛓️ <b>ASIRLAR QO'LLANMASI</b>\n\n"
        "<b>Asirlik cheklovlari:</b>\n"
        "• Asir lord urush e'lon qila olmaydi\n"
        "• Ba'zi amallarga kirish cheklangan\n\n"
        "<b>Ozod qilish:</b>\n"
        "G'olibning lordi asirni ozod qilishi yoki to'lov talab qilishi mumkin.\n\n"
        "<b>Execute (o'ldirish):</b>\n"
        "Asirni o'ldirsa — o'sha xonadon 'o'ldirilgan lord' belgisiga ega bo'ladi.\n"
        "Bu belgili xonadonga istalgan lord hududdan qat'i nazar urush e'lon qila oladi!\n\n"
        "⚠️ Asirlikda urush e'lon qilib bo'lmaydi! Avval ozod bo'lish kerak."
    ),

    "rollar": (
        "👑 <b>ROLLAR VA VAKOLATLAR</b>\n\n"
        "🔧 <b>Admin</b>\n"
        "Barcha huquqlarga ega. Narxlar, urush vaqtlari, custom itemlarni boshqaradi.\n\n"
        "👑 <b>High Lord</b>\n"
        "Hududning hukmdori. Barcha hududlarga urush e'lon qiladi. "
        "Diplomatiya, bozor, asir boshqaruvi. Vassal xonadonlardan soliq oladi.\n\n"
        "⚔️ <b>Lord</b>\n"
        "Xonadon rahbari. Faqat o'z hududidagi xonadonga urush e'lon qiladi. "
        "Diplomatiya, bozor, asir boshqaruvi vakolati bor.\n\n"
        "🗡️ <b>Member (A'zo)</b>\n"
        "Oddiy xonadon a'zosi. Urush paytida xiyonat qila oladi. "
        "Asosiy o'yin funksiyalaridan foydalanadi."
    ),
}


@router.message(F.text == "📖 Qo'llanma")
async def guide_main(message: Message):
    await message.answer(
        GUIDE_TEXT["main"],
        reply_markup=guide_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "guide:urush")
async def guide_urush(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        GUIDE_TEXT["urush"],
        reply_markup=guide_keyboard(back=True),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "guide:jang")
async def guide_jang(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        GUIDE_TEXT["jang"],
        reply_markup=guide_keyboard(back=True),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "guide:diplo")
async def guide_diplo(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        GUIDE_TEXT["diplo"],
        reply_markup=guide_keyboard(back=True),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "guide:bozor")
async def guide_bozor(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        GUIDE_TEXT["bozor"],
        reply_markup=guide_keyboard(back=True),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "guide:asir")
async def guide_asir(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        GUIDE_TEXT["asir"],
        reply_markup=guide_keyboard(back=True),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "guide:rollar")
async def guide_rollar(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        GUIDE_TEXT["rollar"],
        reply_markup=guide_keyboard(back=True),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "guide:back")
async def guide_back(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        GUIDE_TEXT["main"],
        reply_markup=guide_keyboard(),
        parse_mode="HTML"
    )
