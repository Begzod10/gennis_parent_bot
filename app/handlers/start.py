import logging
import requests

from aiogram import Router, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext

from app.config import TECH_API
from app.db import SessionLocal
from app.i18n import t
from app.models import ParentSubscription, UserSettings
from app.keyboards import language_keyboard, main_keyboard, results_keyboard, child_keyboard
from app.states import Form

logger = logging.getLogger(__name__)
router = Router()

_BACK_TEXTS = ("⬅️ Ortga", "⬅️ Назад")
_UNSUB_TEXTS = ("❌ Obunani bekor qilish", "❌ Отменить подписку")


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_lang(telegram_id: int) -> str:
    with SessionLocal() as db:
        s = db.query(UserSettings).filter_by(telegram_id=telegram_id).first()
        return s.lang if s else "uz"


def set_lang(telegram_id: int, lang: str) -> None:
    with SessionLocal() as db:
        s = db.query(UserSettings).filter_by(telegram_id=telegram_id).first()
        if s:
            s.lang = lang
        else:
            db.add(UserSettings(telegram_id=telegram_id, lang=lang))
        db.commit()


# ── /start ────────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(Form.awaiting_lang)
    await message.answer(t("uz", "choose_lang"), reply_markup=language_keyboard())


# ── Language selection ────────────────────────────────────────────────────────

@router.message(Form.awaiting_lang, F.text.in_(["🇺🇿 O'zbek", "🇷🇺 Русский"]))
async def handle_lang_choice(message: types.Message, state: FSMContext) -> None:
    lang = "uz" if "O'zbek" in (message.text or "") else "ru"
    set_lang(message.from_user.id, lang)
    await state.clear()
    await message.answer(
        t(lang, "lang_set") + "\n\n" + t(lang, "welcome"),
        reply_markup=main_keyboard(lang),
    )


@router.message(Form.awaiting_lang)
async def awaiting_lang_fallback(message: types.Message) -> None:
    await message.answer(t("uz", "choose_lang"), reply_markup=language_keyboard())


# ── Language switch from main menu ────────────────────────────────────────────

@router.message(F.text.in_(["🌐 Til: O'zbek", "🌐 Язык: Русский"]))
async def switch_language(message: types.Message, state: FSMContext) -> None:
    await state.set_state(Form.awaiting_lang)
    await message.answer(t("uz", "choose_lang"), reply_markup=language_keyboard())


# ── Search ────────────────────────────────────────────────────────────────────

@router.message(F.text.in_(["🔍 Farzandimni qidirish", "🔍 Найти ребёнка"]))
async def ask_child_name(message: types.Message, state: FSMContext) -> None:
    lang = get_lang(message.from_user.id)
    await state.set_state(Form.awaiting_name)
    await message.answer(t(lang, "ask_name"), reply_markup=results_keyboard([], lang))


@router.message(Form.awaiting_name)
async def handle_name_search(message: types.Message, state: FSMContext) -> None:
    lang = get_lang(message.from_user.id)
    text = (message.text or "").strip()

    if text in _BACK_TEXTS:
        await state.clear()
        await message.answer(t(lang, "main_menu"), reply_markup=main_keyboard(lang))
        return

    if len(text) < 2:
        await message.answer(t(lang, "search_too_short"), reply_markup=results_keyboard([], lang))
        return

    try:
        resp = requests.get(f"{TECH_API}/search-student", params={"q": text}, timeout=10)
        resp.raise_for_status()
        students = resp.json()
    except Exception as e:
        logger.error("Search error: %s", e)
        await state.clear()
        await message.answer(t(lang, "search_error"), reply_markup=main_keyboard(lang))
        return

    if not students:
        await message.answer(
            t(lang, "not_found", q=text),
            reply_markup=results_keyboard([], lang),
        )
        return

    names = [s["name"] for s in students]
    await state.set_state(Form.choosing_student)
    await state.update_data(search_results=students)
    await message.answer(
        t(lang, "found", n=len(students)),
        reply_markup=results_keyboard(names, lang),
    )


@router.message(Form.choosing_student)
async def handle_student_choice(message: types.Message, state: FSMContext) -> None:
    lang = get_lang(message.from_user.id)
    text = (message.text or "").strip()

    if text in _BACK_TEXTS:
        await state.clear()
        await message.answer(t(lang, "main_menu"), reply_markup=main_keyboard(lang))
        return

    data = await state.get_data()
    results = data.get("search_results", [])
    student = next((s for s in results if s["name"] == text), None)

    if not student:
        await state.clear()
        await message.answer(t(lang, "main_menu"), reply_markup=main_keyboard(lang))
        return

    with SessionLocal() as db:
        existing = db.query(ParentSubscription).filter_by(
            telegram_id=message.from_user.id,
            student_platform_id=student["id"],
            is_active=True,
        ).first()
        if existing:
            await state.clear()
            await message.answer(
                t(lang, "already_subscribed"), reply_markup=main_keyboard(lang)
            )
            return

        db.add(ParentSubscription(
            telegram_id=message.from_user.id,
            parent_name=message.from_user.full_name,
            student_platform_id=student["id"],
            student_name=student["name"],
        ))
        db.commit()

    await state.clear()
    await message.answer(
        t(lang, "subscribed", name=student["name"]),
        reply_markup=main_keyboard(lang),
    )


# ── My children ───────────────────────────────────────────────────────────────

@router.message(F.text.in_(["👨‍👧 Farzandlarim ro'yxati", "👨‍👧 Мои дети"]))
async def my_children(message: types.Message, state: FSMContext) -> None:
    lang = get_lang(message.from_user.id)
    with SessionLocal() as db:
        subs = db.query(ParentSubscription).filter_by(
            telegram_id=message.from_user.id, is_active=True
        ).all()
        subs_list = [
            {"sub_id": s.id, "student_id": s.student_platform_id, "name": s.student_name}
            for s in subs
        ]

    if not subs_list:
        await message.answer(t(lang, "no_subs"), reply_markup=main_keyboard(lang))
        return

    names = [s["name"] for s in subs_list]
    await state.set_state(Form.viewing_child)
    await state.update_data(subscriptions=subs_list, mode="view")
    await message.answer(
        t(lang, "my_children_title", n=len(subs_list)),
        reply_markup=results_keyboard(names, lang),
    )


# ── Unsubscribe from main menu ────────────────────────────────────────────────

@router.message(F.text.in_(list(_UNSUB_TEXTS)))
async def unsubscribe_menu(message: types.Message, state: FSMContext) -> None:
    lang = get_lang(message.from_user.id)
    with SessionLocal() as db:
        subs = db.query(ParentSubscription).filter_by(
            telegram_id=message.from_user.id, is_active=True
        ).all()
        subs_list = [
            {"sub_id": s.id, "student_id": s.student_platform_id, "name": s.student_name}
            for s in subs
        ]

    if not subs_list:
        await message.answer(t(lang, "no_active_subs"), reply_markup=main_keyboard(lang))
        return

    names = [s["name"] for s in subs_list]
    await state.set_state(Form.viewing_child)
    await state.update_data(subscriptions=subs_list, mode="unsubscribe")
    await message.answer(t(lang, "ask_unsub"), reply_markup=results_keyboard(names, lang))


# ── Viewing child (stats + unsubscribe) ───────────────────────────────────────

@router.message(Form.viewing_child)
async def handle_child_action(message: types.Message, state: FSMContext) -> None:
    lang = get_lang(message.from_user.id)
    text = (message.text or "").strip()
    data = await state.get_data()

    if text in _BACK_TEXTS:
        await state.clear()
        await message.answer(t(lang, "main_menu"), reply_markup=main_keyboard(lang))
        return

    # Unsubscribe button when a specific child is being viewed
    if text in _UNSUB_TEXTS:
        sub_id = data.get("active_sub_id")
        sub_name = data.get("active_sub_name", "")
        if sub_id:
            with SessionLocal() as db:
                sub = db.query(ParentSubscription).filter_by(
                    id=sub_id, telegram_id=message.from_user.id
                ).first()
                if sub:
                    sub.is_active = False
                    db.commit()
        await state.clear()
        await message.answer(
            t(lang, "unsubbed", name=sub_name),
            reply_markup=main_keyboard(lang),
        )
        return

    # Child name tapped from list
    subscriptions = data.get("subscriptions", [])
    mode = data.get("mode", "view")
    sub = next((s for s in subscriptions if s["name"] == text), None)

    if not sub:
        await state.clear()
        await message.answer(t(lang, "main_menu"), reply_markup=main_keyboard(lang))
        return

    if mode == "unsubscribe":
        with SessionLocal() as db:
            s = db.query(ParentSubscription).filter_by(
                id=sub["sub_id"], telegram_id=message.from_user.id
            ).first()
            if s:
                s.is_active = False
                db.commit()
        await state.clear()
        await message.answer(
            t(lang, "unsubbed", name=sub["name"]),
            reply_markup=main_keyboard(lang),
        )
        return

    # mode == "view": fetch and show stats
    await state.update_data(active_sub_id=sub["sub_id"], active_sub_name=sub["name"])
    try:
        resp = requests.get(f"{TECH_API}/student-stats/{sub['student_id']}", timeout=10)
        resp.raise_for_status()
        stats_data = resp.json()
        stats_text = format_stats(stats_data, lang)
    except Exception as e:
        logger.error("Stats error for student %s: %s", sub["student_id"], e)
        stats_text = t(lang, "stats_error")

    await message.answer(stats_text, reply_markup=child_keyboard(lang))


# ── Stats formatter ───────────────────────────────────────────────────────────

def format_stats(data: dict, lang: str) -> str:
    name = data.get("name") or "O'quvchi"
    text = (
        t(lang, "stats_title", name=name)
        + t(lang, "total_pts", v=data.get("total_points", 0))
        + t(lang, "weekly_pts", v=data.get("weekly_points", 0))
        + t(lang, "rank", v=data.get("global_rank", 0))
        + t(lang, "separator")
    )

    status_emoji = {"Submitted": "⏳", "Approved": "✅", "Rejected": "❌", "Pending": "🔄"}

    for c in data.get("courses", []):
        done = c.get("lessons_completed", 0)
        total = c.get("lessons_total", 0)
        pct = round(done / total * 100) if total else 0
        ex = c.get("exercises", {})
        bar = _progress_bar(pct)

        text += f"\n📘 <b>{c['title']}</b>  {bar} {pct}%\n"
        text += t(lang, "lessons", done=done, total=total)
        text += t(lang, "exercises", correct=ex.get("correct", 0), total=ex.get("total", 0))

        for p in c.get("projects", []):
            emoji = status_emoji.get(p.get("status", ""), "📌")
            grade = t(lang, "grade_label", v=p["grade"]) if p.get("grade") else ""
            pts = t(lang, "pts_label", v=p["points"]) if p.get("points") else ""
            text += t(lang, "project_line", emoji=emoji, grade=grade, pts=pts)

    return text


def _progress_bar(pct: int) -> str:
    filled = round(pct / 10)
    return "█" * filled + "░" * (10 - filled)
