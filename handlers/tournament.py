"""
Turnir tizimi:
  - Admin turnir yaratadi (sarlavha, vaqt, savollar, mukofotlar)
  - Lord o'z xonadonidan ritsar saylaydi
  - Turnir boshlananda faqat ritsarlarga savollar ketma-ket yuboriladi
  - To'g'ri javob avtomatik hisoblanadi
  - Turnir tugaganda 1-2-3 o'rin e'lon qilinadi, mukofot xonadon xazinasiga tushadi
  - Xronikaga va barcha xonadonga xabar ketadi
"""

import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config.settings import settings
from database.engine import AsyncSessionFactory
from database.models import (
    RoleEnum, TournamentStatusEnum,
    Tournament, TournamentQuestion, TournamentAnswer,
    House, User
)
from sqlalchemy import select, update, func
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)
router = Router()


# ─── FSM holatlari ────────────────────────────────────────────────────────────

class TournamentCreateFSM(StatesGroup):
    title     = State()
    starts_at = State()
    ends_at   = State()
    prize_1   = State()
    prize_2   = State()
    prize_3   = State()
    # Savollar qo'shish
    q_text    = State()
    q_opt_a   = State()
    q_opt_b   = State()
    q_opt_c   = State()
    q_opt_d   = State()
    q_correct = State()
    q_points  = State()
    q_more    = State()   # Yana savol qo'shish yoki tugatish


class KnightSelectFSM(StatesGroup):
    waiting = State()   # Lord a'zo tanlayapti


# ─── Yordamchi funksiyalar ────────────────────────────────────────────────────

def _is_admin(user_id: int) -> bool:
    return user_id in settings.ADMIN_IDS


def _question_keyboard(question: TournamentQuestion) -> InlineKeyboardMarkup:
    """Savolga variantli inline tugmalar"""
    builder = InlineKeyboardBuilder()
    builder.button(text=f"🅰️  {question.option_a}", callback_data=f"tourn_ans:{question.id}:a")
    builder.button(text=f"🅱️  {question.option_b}", callback_data=f"tourn_ans:{question.id}:b")
    if question.option_c:
        builder.button(text=f"🇨  {question.option_c}", callback_data=f"tourn_ans:{question.id}:c")
    if question.option_d:
        builder.button(text=f"🇩  {question.option_d}", callback_data=f"tourn_ans:{question.id}:d")
    builder.adjust(1)
    return builder.as_markup()


async def _get_active_tournament(session) -> Tournament | None:
    result = await session.execute(
        select(Tournament)
        .where(Tournament.status == TournamentStatusEnum.ACTIVE)
        .options(selectinload(Tournament.questions).selectinload(TournamentQuestion.answers))
        .order_by(Tournament.id.desc())
    )
    return result.scalars().first()


async def _get_pending_tournament(session) -> Tournament | None:
    result = await session.execute(
        select(Tournament)
        .where(Tournament.status == TournamentStatusEnum.PENDING)
        .options(selectinload(Tournament.questions))
        .order_by(Tournament.id.desc())
    )
    return result.scalars().first()


async def _send_next_question(bot, knight_id: int, tournament: Tournament, session):
    """Ritsarga keyingi javob berilmagan savolni yuboradi"""
    # Allaqachon javob berilgan savollar
    answered_result = await session.execute(
        select(TournamentAnswer.question_id).where(
            TournamentAnswer.knight_id == knight_id,
            TournamentAnswer.tournament_id == tournament.id,
        )
    )
    answered_ids = {row[0] for row in answered_result.all()}

    # Navbatdagi savol
    next_q = None
    for q in tournament.questions:
        if q.id not in answered_ids:
            next_q = q
            break

    if next_q is None:
        await bot.send_message(knight_id,
            "✅ <b>Barcha savollarga javob berdingiz!</b>\n"
            "Turnir natijalarini kuting. 🏆",
            parse_mode="HTML"
        )
        return

    total = len(tournament.questions)
    num   = len(answered_ids) + 1
    text  = (
        f"⚔️ <b>TURNIR: {tournament.title}</b>\n\n"
        f"📌 Savol {num}/{total}:\n\n"
        f"<b>{next_q.text}</b>\n\n"
        f"🏅 Ball: <b>{next_q.points}</b>"
    )
    await bot.send_message(
        knight_id, text,
        reply_markup=_question_keyboard(next_q),
        parse_mode="HTML"
    )


async def _broadcast_to_all_houses(bot, text: str):
    """Barcha lord va a'zolarga xabar yuborish"""
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(User).where(
                User.is_active == True,
                User.house_id.isnot(None),
            )
        )
        users = result.scalars().all()
        for u in users:
            try:
                await bot.send_message(u.id, text, parse_mode="HTML")
            except Exception:
                pass


# ─── ADMIN: Turnir yaratish ───────────────────────────────────────────────────

@router.message(F.text == "🏆 Turnir boshqaruvi")
async def admin_tournament_menu(message: Message):
    if not _is_admin(message.from_user.id):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Yangi Turnir Yaratish", callback_data="tourn:create")],
        [InlineKeyboardButton(text="▶️ Turnirni Boshlash",    callback_data="tourn:start")],
        [InlineKeyboardButton(text="🏁 Turnirni Tugatish",    callback_data="tourn:finish")],
        [InlineKeyboardButton(text="📊 Joriy Holat",          callback_data="tourn:status")],
    ])
    await message.answer("🏆 <b>Turnir Boshqaruvi</b>", reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "tourn:create")
async def tourn_create_start(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        return
    await call.message.answer("📝 Turnir sarlavhasini kiriting:")
    await state.set_state(TournamentCreateFSM.title)
    await call.answer()


@router.message(TournamentCreateFSM.title)
async def tourn_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await message.answer(
        "⏰ Turnir <b>boshlanish</b> vaqtini kiriting (format: <code>YYYY-MM-DD HH:MM</code>)\n"
        "Masalan: <code>2025-06-01 19:00</code>",
        parse_mode="HTML"
    )
    await state.set_state(TournamentCreateFSM.starts_at)


@router.message(TournamentCreateFSM.starts_at)
async def tourn_starts_at(message: Message, state: FSMContext):
    try:
        dt = datetime.strptime(message.text.strip(), "%Y-%m-%d %H:%M")
    except ValueError:
        await message.answer("❌ Noto'g'ri format. Qayta kiriting (YYYY-MM-DD HH:MM):")
        return
    await state.update_data(starts_at=dt)
    await message.answer(
        "⏰ Turnir <b>tugash</b> vaqtini kiriting (format: <code>YYYY-MM-DD HH:MM</code>):",
        parse_mode="HTML"
    )
    await state.set_state(TournamentCreateFSM.ends_at)


@router.message(TournamentCreateFSM.ends_at)
async def tourn_ends_at(message: Message, state: FSMContext):
    try:
        dt = datetime.strptime(message.text.strip(), "%Y-%m-%d %H:%M")
    except ValueError:
        await message.answer("❌ Noto'g'ri format. Qayta kiriting (YYYY-MM-DD HH:MM):")
        return
    await state.update_data(ends_at=dt)
    await message.answer("🥇 <b>1-o'rin mukofoti</b> (tanga):", parse_mode="HTML")
    await state.set_state(TournamentCreateFSM.prize_1)


@router.message(TournamentCreateFSM.prize_1)
async def tourn_prize1(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Faqat raqam kiriting:")
        return
    await state.update_data(prize_1=int(message.text))
    await message.answer("🥈 <b>2-o'rin mukofoti</b> (tanga):", parse_mode="HTML")
    await state.set_state(TournamentCreateFSM.prize_2)


@router.message(TournamentCreateFSM.prize_2)
async def tourn_prize2(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Faqat raqam kiriting:")
        return
    await state.update_data(prize_2=int(message.text))
    await message.answer("🥉 <b>3-o'rin mukofoti</b> (tanga):", parse_mode="HTML")
    await state.set_state(TournamentCreateFSM.prize_3)


@router.message(TournamentCreateFSM.prize_3)
async def tourn_prize3(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Faqat raqam kiriting:")
        return
    await state.update_data(prize_3=int(message.text), questions=[])
    await message.answer(
        "✅ Mukofotlar saqlandi!\n\n"
        "📋 Endi <b>1-savolni</b> kiriting:",
        parse_mode="HTML"
    )
    await state.set_state(TournamentCreateFSM.q_text)


@router.message(TournamentCreateFSM.q_text)
async def tourn_q_text(message: Message, state: FSMContext):
    await state.update_data(cur_q_text=message.text.strip())
    await message.answer("🅰️ <b>A variant</b>ni kiriting:", parse_mode="HTML")
    await state.set_state(TournamentCreateFSM.q_opt_a)


@router.message(TournamentCreateFSM.q_opt_a)
async def tourn_opt_a(message: Message, state: FSMContext):
    await state.update_data(cur_q_a=message.text.strip())
    await message.answer("🅱️ <b>B variant</b>ni kiriting:", parse_mode="HTML")
    await state.set_state(TournamentCreateFSM.q_opt_b)


@router.message(TournamentCreateFSM.q_opt_b)
async def tourn_opt_b(message: Message, state: FSMContext):
    await state.update_data(cur_q_b=message.text.strip())
    await message.answer(
        "🇨 <b>C variant</b>ni kiriting (yoki <code>-</code> o'tkazib yuborish):",
        parse_mode="HTML"
    )
    await state.set_state(TournamentCreateFSM.q_opt_c)


@router.message(TournamentCreateFSM.q_opt_c)
async def tourn_opt_c(message: Message, state: FSMContext):
    val = None if message.text.strip() == "-" else message.text.strip()
    await state.update_data(cur_q_c=val)
    await message.answer(
        "🇩 <b>D variant</b>ni kiriting (yoki <code>-</code> o'tkazib yuborish):",
        parse_mode="HTML"
    )
    await state.set_state(TournamentCreateFSM.q_opt_d)


@router.message(TournamentCreateFSM.q_opt_d)
async def tourn_opt_d(message: Message, state: FSMContext):
    val = None if message.text.strip() == "-" else message.text.strip()
    await state.update_data(cur_q_d=val)
    data = await state.get_data()
    # To'g'ri javob variantlarini aniqlash
    opts = ["a", "b"]
    if data.get("cur_q_c"):
        opts.append("c")
    if data.get("cur_q_d"):
        opts.append("d")
    await message.answer(
        f"✅ To'g'ri javobni tanlang: {' / '.join(opts.upper() if False else [o.upper() for o in opts])}\n"
        f"(kichik harf bilan: {' / '.join(opts)})"
    )
    await state.set_state(TournamentCreateFSM.q_correct)


@router.message(TournamentCreateFSM.q_correct)
async def tourn_q_correct(message: Message, state: FSMContext):
    val = message.text.strip().lower()
    if val not in ("a", "b", "c", "d"):
        await message.answer("❌ Faqat a, b, c yoki d kiriting:")
        return
    await state.update_data(cur_q_correct=val)
    await message.answer("🏅 Bu savol uchun <b>ball miqdori</b>ni kiriting (masalan: 1, 2, 5):", parse_mode="HTML")
    await state.set_state(TournamentCreateFSM.q_points)


@router.message(TournamentCreateFSM.q_points)
async def tourn_q_points(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("❌ Faqat raqam kiriting:")
        return
    data = await state.get_data()
    questions: list = data.get("questions", [])
    questions.append({
        "order_num": len(questions) + 1,
        "text":      data["cur_q_text"],
        "option_a":  data["cur_q_a"],
        "option_b":  data["cur_q_b"],
        "option_c":  data.get("cur_q_c"),
        "option_d":  data.get("cur_q_d"),
        "correct":   data["cur_q_correct"],
        "points":    int(message.text.strip()),
    })
    await state.update_data(questions=questions)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Yana savol qo'shish", callback_data="tourn_q:more")],
        [InlineKeyboardButton(text="✅ Turnirni saqlash",     callback_data="tourn_q:save")],
    ])
    await message.answer(
        f"✅ Savol {len(questions)} saqlandi!\n\nNima qilasiz?",
        reply_markup=kb
    )
    await state.set_state(TournamentCreateFSM.q_more)


@router.callback_query(TournamentCreateFSM.q_more, F.data == "tourn_q:more")
async def tourn_add_more(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    n = len(data.get("questions", [])) + 1
    await call.message.answer(f"📋 <b>{n}-savolni</b> kiriting:", parse_mode="HTML")
    await state.set_state(TournamentCreateFSM.q_text)
    await call.answer()


@router.callback_query(TournamentCreateFSM.q_more, F.data == "tourn_q:save")
async def tourn_save(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    questions = data.get("questions", [])
    if not questions:
        await call.answer("Kamida 1 ta savol kerak!", show_alert=True)
        return

    async with AsyncSessionFactory() as session:
        t = Tournament(
            title      = data["title"],
            prize_1    = data["prize_1"],
            prize_2    = data["prize_2"],
            prize_3    = data["prize_3"],
            starts_at  = data["starts_at"],
            ends_at    = data["ends_at"],
            created_by = call.from_user.id,
            status     = TournamentStatusEnum.PENDING,
        )
        session.add(t)
        await session.flush()
        for q in questions:
            session.add(TournamentQuestion(tournament_id=t.id, **q))
        await session.commit()
        tid = t.id

    await state.clear()
    await call.message.answer(
        f"✅ <b>Turnir #{tid} saqlandi!</b>\n"
        f"📌 Sarlavha: {data['title']}\n"
        f"📋 Savollar: {len(questions)} ta\n"
        f"🥇 {data['prize_1']} | 🥈 {data['prize_2']} | 🥉 {data['prize_3']} tanga\n\n"
        f"Turnirni boshlash uchun <b>▶️ Turnirni Boshlash</b> ni bosing.",
        parse_mode="HTML"
    )
    await call.answer()


# ─── ADMIN: Turnirni boshlash ─────────────────────────────────────────────────

@router.callback_query(F.data == "tourn:start")
async def tourn_start(call: CallbackQuery, bot):
    if not _is_admin(call.from_user.id):
        return
    async with AsyncSessionFactory() as session:
        t = await _get_pending_tournament(session)
        if not t:
            await call.answer("Kutayotgan turnir topilmadi!", show_alert=True)
            return

        t.status = TournamentStatusEnum.ACTIVE
        await session.commit()
        tid   = t.id
        title = t.title
        p1, p2, p3 = t.prize_1, t.prize_2, t.prize_3
        q_count = len(t.questions)

        # Barcha ritsarlarni topish
        knights_result = await session.execute(
            select(User).where(User.role == RoleEnum.KNIGHT, User.is_active == True)
        )
        knights = knights_result.scalars().all()
        knight_ids = [k.id for k in knights]

    # Barcha xonadonga e'lon
    announce = (
        f"⚔️ <b>TURNIR BOSHLANDI!</b>\n\n"
        f"🏆 <b>{title}</b>\n\n"
        f"📋 Savollar soni: {q_count}\n"
        f"🥇 1-o'rin: <b>{p1:,}</b> tanga\n"
        f"🥈 2-o'rin: <b>{p2:,}</b> tanga\n"
        f"🥉 3-o'rin: <b>{p3:,}</b> tanga\n\n"
        f"Faqat ritsarlar ishtirok etadi. Omad! ⚔️"
    )
    await _broadcast_to_all_houses(bot, announce)

    # Xronikaga yozish
    from utils.chronicle import post_to_chronicle
    await post_to_chronicle(bot, f"⚔️ <b>TURNIR BOSHLANDI: {title}</b>\n🏅 Mukofot: {p1}+{p2}+{p3} tanga")

    # Ritsarlarga birinchi savolni yuborish
    async with AsyncSessionFactory() as session:
        t = await _get_active_tournament(session)
        for kid in knight_ids:
            try:
                await _send_next_question(bot, kid, t, session)
            except Exception as e:
                logger.error(f"Ritsarga savol yuborishda xato {kid}: {e}")

    await call.answer(f"✅ Turnir boshlandi! {len(knight_ids)} ta ritsarga savol yuborildi.")


# ─── RITSAR: Savolga javob berish ────────────────────────────────────────────

@router.callback_query(F.data.startswith("tourn_ans:"))
async def tourn_answer(call: CallbackQuery, bot):
    # Format: tourn_ans:{question_id}:{chosen}
    parts = call.data.split(":")
    if len(parts) != 3:
        await call.answer("Xato format!", show_alert=True)
        return
    question_id = int(parts[1])
    chosen      = parts[2]

    async with AsyncSessionFactory() as session:
        # Foydalanuvchi ritsarmi?
        user_result = await session.execute(
            select(User).where(User.id == call.from_user.id)
        )
        user = user_result.scalar_one_or_none()
        if not user or user.role != RoleEnum.KNIGHT:
            await call.answer("Faqat ritsarlar turnirda qatnasha oladi!", show_alert=True)
            return

        # Savol mavjudmi?
        q_result = await session.execute(
            select(TournamentQuestion)
            .options(selectinload(TournamentQuestion.tournament))
            .where(TournamentQuestion.id == question_id)
        )
        question = q_result.scalar_one_or_none()
        if not question:
            await call.answer("Savol topilmadi!", show_alert=True)
            return

        t = question.tournament
        if t.status != TournamentStatusEnum.ACTIVE:
            await call.answer("Bu turnir hozir faol emas!", show_alert=True)
            return

        # Allaqachon javob berganmi?
        existing = await session.execute(
            select(TournamentAnswer).where(
                TournamentAnswer.question_id == question_id,
                TournamentAnswer.knight_id   == call.from_user.id,
            )
        )
        if existing.scalar_one_or_none():
            await call.answer("Bu savolga allaqachon javob berdingiz!", show_alert=True)
            return

        is_correct = (chosen == question.correct)
        answer = TournamentAnswer(
            tournament_id = t.id,
            question_id   = question_id,
            knight_id     = call.from_user.id,
            chosen        = chosen,
            is_correct    = is_correct,
        )
        session.add(answer)
        await session.commit()

        # Tugmalarni o'chirish
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

        if is_correct:
            await call.answer(f"✅ To'g'ri! +{question.points} ball", show_alert=True)
            await call.message.answer(f"✅ <b>To'g'ri javob!</b> +{question.points} ball 🎉", parse_mode="HTML")
        else:
            # To'g'ri javobni ko'rsatish
            correct_map = {
                "a": question.option_a,
                "b": question.option_b,
                "c": question.option_c,
                "d": question.option_d,
            }
            correct_text = correct_map.get(question.correct, "?")
            await call.answer("❌ Noto'g'ri javob!", show_alert=True)
            await call.message.answer(
                f"❌ <b>Noto'g'ri!</b>\n"
                f"To'g'ri javob: <b>{question.correct.upper()}) {correct_text}</b>",
                parse_mode="HTML"
            )

        # Keyingi savolni yuborish
        t_fresh_result = await session.execute(
            select(Tournament)
            .where(Tournament.id == t.id)
            .options(selectinload(Tournament.questions).selectinload(TournamentQuestion.answers))
        )
        t_fresh = t_fresh_result.scalar_one_or_none()
        if t_fresh:
            await _send_next_question(bot, call.from_user.id, t_fresh, session)


# ─── ADMIN: Turnirni tugatish ─────────────────────────────────────────────────

@router.callback_query(F.data == "tourn:finish")
async def tourn_finish(call: CallbackQuery, bot):
    if not _is_admin(call.from_user.id):
        return
    async with AsyncSessionFactory() as session:
        t = await _get_active_tournament(session)
        if not t:
            await call.answer("Faol turnir topilmadi!", show_alert=True)
            return
        await _finish_tournament(session, t, bot)
    await call.answer("✅ Turnir yakunlandi!")


async def _finish_tournament(session, tournament: Tournament, bot):
    """Turnirni yakunlash, natijalar hisoblash, mukofot berish"""
    from database.models import House

    tournament.status = TournamentStatusEnum.FINISHED
    await session.commit()

    # Har bir ritsarning ballini hisoblash
    knights_result = await session.execute(
        select(User).where(User.role == RoleEnum.KNIGHT, User.is_active == True)
    )
    knights = knights_result.scalars().all()

    scores = []
    for k in knights:
        ans_result = await session.execute(
            select(
                func.sum(TournamentQuestion.points)
            ).join(
                TournamentAnswer,
                TournamentAnswer.question_id == TournamentQuestion.id
            ).where(
                TournamentAnswer.knight_id   == k.id,
                TournamentAnswer.tournament_id == tournament.id,
                TournamentAnswer.is_correct  == True,
            )
        )
        pts = ans_result.scalar_one_or_none() or 0
        scores.append((k, pts))

    scores.sort(key=lambda x: x[1], reverse=True)

    prizes = [tournament.prize_1, tournament.prize_2, tournament.prize_3]
    result_lines = [f"🏆 <b>TURNIR YAKUNLANDI: {tournament.title}</b>\n"]

    medals = ["🥇", "🥈", "🥉"]
    for i, (knight, pts) in enumerate(scores[:3]):
        medal   = medals[i] if i < 3 else "🎖"
        prize   = prizes[i] if i < len(prizes) else 0
        # Xonadon xazinasiga mukofot
        if prize > 0 and knight.house_id:
            await session.execute(
                update(House).where(House.id == knight.house_id)
                .values(treasury=House.treasury + prize)
            )
        result_lines.append(
            f"{medal} {i+1}-o'rin: <b>{knight.full_name}</b> — {pts} ball"
            + (f" | +{prize:,} tanga" if prize > 0 else "")
        )
        # Ritsarga shaxsiy xabar
        try:
            await bot.send_message(
                knight.id,
                f"{medal} Siz turnirda <b>{i+1}-o'rin</b> oldingiz!\n"
                f"Ball: <b>{pts}</b>"
                + (f"\nXonadon xazinasiga <b>{prize:,} tanga</b> qo'shildi! 🎉" if prize > 0 else ""),
                parse_mode="HTML"
            )
        except Exception:
            pass

    if len(scores) > 3:
        result_lines.append(f"\n...va boshqa {len(scores)-3} ishtirokchi")

    await session.commit()

    full_text = "\n".join(result_lines)

    # Barcha xonadonga e'lon
    await _broadcast_to_all_houses(bot, full_text)

    # Xronikaga
    from utils.chronicle import post_to_chronicle
    await post_to_chronicle(bot, full_text)


# ─── ADMIN: Turnir holati ─────────────────────────────────────────────────────

@router.callback_query(F.data == "tourn:status")
async def tourn_status(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        return
    async with AsyncSessionFactory() as session:
        t = await _get_active_tournament(session)
        if not t:
            t = await _get_pending_tournament(session)
        if not t:
            await call.message.answer("Hozir faol yoki kutayotgan turnir yo'q.")
            await call.answer()
            return

        knights_result = await session.execute(
            select(User).where(User.role == RoleEnum.KNIGHT, User.is_active == True)
        )
        knights = knights_result.scalars().all()
        lines = [f"⚔️ <b>{t.title}</b> | Holat: {t.status.value}\n"]
        for k in knights:
            ans_result = await session.execute(
                select(func.count(TournamentAnswer.id)).where(
                    TournamentAnswer.knight_id    == k.id,
                    TournamentAnswer.tournament_id == t.id,
                    TournamentAnswer.is_correct   == True,
                )
            )
            pts = ans_result.scalar_one() or 0
            lines.append(f"⚔️ {k.full_name}: {pts} ball")

    await call.message.answer("\n".join(lines) or "Hali natija yo'q.", parse_mode="HTML")
    await call.answer()


# ─── LORD: Ritsar saylash ─────────────────────────────────────────────────────

@router.message(F.text == "⚔️ Ritsar Saylash")
async def lord_select_knight(message: Message, state: FSMContext):
    async with AsyncSessionFactory() as session:
        user_result = await session.execute(
            select(User).where(User.id == message.from_user.id)
        )
        user = user_result.scalar_one_or_none()
        if not user or user.role not in [RoleEnum.LORD, RoleEnum.HIGH_LORD, RoleEnum.ADMIN]:
            await message.answer("⛔ Faqat lord ritsar sayla oladi.")
            return

        house_result = await session.execute(
            select(House).where(House.id == user.house_id)
            .options(selectinload(House.members))
        )
        house = house_result.scalar_one_or_none()
        if not house:
            await message.answer("Xonadon topilmadi.")
            return

        members = [m for m in house.members if m.id != user.id and m.role == RoleEnum.MEMBER]
        if not members:
            await message.answer("Xonadonda ritsar saylash mumkin bo'lgan a'zo yo'q.")
            return

        current_knight_id = house.knight_id
        kb_buttons = []
        for m in members:
            label = f"⚔️ {m.full_name}"
            if m.id == current_knight_id:
                label += " (joriy ritsar)"
            kb_buttons.append([InlineKeyboardButton(
                text=label, callback_data=f"knight_select:{m.id}"
            )])
        kb_buttons.append([InlineKeyboardButton(text="❌ Bekor qilish", callback_data="knight_select:cancel")])
        kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)

        await message.answer(
            f"⚔️ <b>{house.name}</b> xonadoni uchun ritsar tanlang:\n"
            f"(Ritsar faqat turnirda xonadon uchun tanga ishlaydi)",
            reply_markup=kb, parse_mode="HTML"
        )


@router.callback_query(F.data.startswith("knight_select:"))
async def lord_knight_chosen(call: CallbackQuery, state: FSMContext):
    val = call.data.split(":")[1]
    if val == "cancel":
        await call.message.edit_text("❌ Ritsar saylash bekor qilindi.")
        await call.answer()
        return

    member_id = int(val)
    async with AsyncSessionFactory() as session:
        # Lord tekshiruv
        lord_result = await session.execute(
            select(User).where(User.id == call.from_user.id)
        )
        lord = lord_result.scalar_one_or_none()
        if not lord or lord.role not in [RoleEnum.LORD, RoleEnum.HIGH_LORD, RoleEnum.ADMIN]:
            await call.answer("⛔ Ruxsatsiz!", show_alert=True)
            return

        # A'zo shu xonadondami?
        member_result = await session.execute(
            select(User).where(User.id == member_id, User.house_id == lord.house_id)
        )
        member = member_result.scalar_one_or_none()
        if not member:
            await call.answer("A'zo topilmadi!", show_alert=True)
            return

        # Eski ritsarni MEMBER ga qaytarish
        old_knight_result = await session.execute(
            select(User).where(
                User.house_id == lord.house_id,
                User.role     == RoleEnum.KNIGHT,
            )
        )
        old_knight = old_knight_result.scalar_one_or_none()
        if old_knight:
            old_knight.role = RoleEnum.MEMBER
            try:
                await call.bot.send_message(
                    old_knight.id,
                    "⚔️ Siz endi ritsar emassiz. Lordingiz yangi ritsar sayladi.",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        # Yangi ritsarni tayinlash
        member.role = RoleEnum.KNIGHT
        await session.execute(
            update(House).where(House.id == lord.house_id).values(knight_id=member_id)
        )
        await session.commit()

        house_result = await session.execute(
            select(House).where(House.id == lord.house_id)
        )
        house = house_result.scalar_one_or_none()
        house_name = house.name if house else "Xonadon"

    await call.message.edit_text(
        f"✅ <b>{member.full_name}</b> endi <b>{house_name}</b> xonadonining ritsari!",
        parse_mode="HTML"
    )

    try:
        await call.bot.send_message(
            member_id,
            f"⚔️ <b>Tabriklaymiz!</b>\n"
            f"Siz <b>{house_name}</b> xonadonining <b>Ritsari</b> bo'ldingiz!\n"
            f"Turnir paytida xonadon uchun tanga ishlaysiz. ⚔️",
            parse_mode="HTML"
        )
    except Exception:
        pass

    await call.answer()
