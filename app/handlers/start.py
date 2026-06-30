import logging
import requests

from aiogram import Router, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app.config import TECH_API
from app.db import SessionLocal
from app.i18n import t
from app.models import ParentSubscription, UserSettings
from app.keyboards import (
    main_keyboard,
    language_keyboard,
    student_search_results_keyboard,
    subscriptions_keyboard,
    unsubscribe_keyboard,
)

logger = logging.getLogger(__name__)
router = Router()


class SearchStates(StatesGroup):
    waiting_for_name = State()


# ── Helpers ──────────────────────────────────────────────────────────────────

def get_lang(telegram_id: int) -> str:
    with SessionLocal() as db:
        settings = db.query(UserSettings).filter_by(telegram_id=telegram_id).first()
        return settings.lang if settings else "uz"


def set_lang(telegram_id: int, lang: str):
    with SessionLocal() as db:
        settings = db.query(UserSettings).filter_by(telegram_id=telegram_id).first()
        if settings:
            settings.lang = lang
        else:
            db.add(UserSettings(telegram_id=telegram_id, lang=lang))
        db.commit()


# ── /start ───────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        t("uz", "choose_lang"),
        reply_markup=language_keyboard()
    )


@router.callback_query(F.data.startswith("setlang_"))
async def set_language(callback: types.CallbackQuery):
    lang = callback.data.split("_")[1]
    set_lang(callback.from_user.id, lang)
    await callback.message.answer(
        t(lang, "lang_set"),
        parse_mode="HTML"
    )
    await callback.message.answer(
        t(lang, "welcome"),
        parse_mode="HTML",
        reply_markup=main_keyboard(lang)
    )
    await callback.answer()


# ── Language switch ───────────────────────────────────────────────────────────

@router.message(F.text.in_(["🌐 Til: O'zbek", "🌐 Язык: Русский"]))
async def switch_language(message: types.Message):
    await message.answer(t("uz", "choose_lang"), reply_markup=language_keyboard())


# ── Search ────────────────────────────────────────────────────────────────────

@router.message(F.text.in_(["🔍 Farzandimni qidirish", "🔍 Найти ребёнка"]))
@router.callback_query(F.data == "add_new")
async def ask_child_name(event, state: FSMContext):
    is_cb = isinstance(event, types.CallbackQuery)
    tg_id = event.from_user.id
    lang = get_lang(tg_id)
    message = event.message if is_cb else event
    if is_cb:
        await event.answer()
    await state.set_state(SearchStates.waiting_for_name)
    await message.answer(t(lang, "ask_name"), parse_mode="HTML")


@router.message(SearchStates.waiting_for_name)
async def handle_name_search(message: types.Message, state: FSMContext):
    lang = get_lang(message.from_user.id)
    query = message.text.strip()

    if len(query) < 2:
        await message.answer(t(lang, "search_too_short"))
        return

    try:
        resp = requests.get(f"{TECH_API}/search-student", params={"q": query}, timeout=10)
        resp.raise_for_status()
        students = resp.json()
    except Exception as e:
        logger.error("Search error: %s", e)
        await message.answer(t(lang, "search_error"))
        await state.clear()
        return

    if not students:
        await message.answer(t(lang, "not_found", q=query), parse_mode="HTML")
        return

    await state.clear()
    await message.answer(
        t(lang, "found", n=len(students)),
        parse_mode="HTML",
        reply_markup=student_search_results_keyboard(students, lang)
    )


@router.callback_query(F.data.startswith("subscribe_"))
async def subscribe_to_student(callback: types.CallbackQuery):
    lang = get_lang(callback.from_user.id)
    parts = callback.data.split("_", 2)
    student_id = int(parts[1])
    student_name = parts[2] if len(parts) > 2 else "O'quvchi"

    with SessionLocal() as db:
        existing = db.query(ParentSubscription).filter_by(
            telegram_id=callback.from_user.id,
            student_platform_id=student_id,
            is_active=True
        ).first()
        if existing:
            await callback.answer(t(lang, "already_subscribed"), show_alert=True)
            return

        db.add(ParentSubscription(
            telegram_id=callback.from_user.id,
            parent_name=callback.from_user.full_name,
            student_platform_id=student_id,
            student_name=student_name,
        ))
        db.commit()

    await callback.message.answer(
        t(lang, "subscribed", name=student_name),
        parse_mode="HTML",
        reply_markup=main_keyboard(lang)
    )
    await callback.answer()


@router.callback_query(F.data == "cancel_search")
async def cancel_search(callback: types.CallbackQuery, state: FSMContext):
    lang = get_lang(callback.from_user.id)
    await state.clear()
    await callback.message.answer(t(lang, "cancel"), reply_markup=main_keyboard(lang))
    await callback.answer()


# ── My children ───────────────────────────────────────────────────────────────

@router.message(F.text.in_(["👨‍👧 Farzandlarim ro'yxati", "👨‍👧 Мои дети"]))
async def my_subscriptions(message: types.Message):
    lang = get_lang(message.from_user.id)
    with SessionLocal() as db:
        subs = db.query(ParentSubscription).filter_by(
            telegram_id=message.from_user.id, is_active=True
        ).all()

    if not subs:
        await message.answer(t(lang, "no_subs"), reply_markup=main_keyboard(lang))
        return

    await message.answer(
        t(lang, "my_children_title", n=len(subs)),
        reply_markup=subscriptions_keyboard(subs, lang)
    )


@router.callback_query(F.data.startswith("view_stats_"))
async def view_student_stats(callback: types.CallbackQuery):
    lang = get_lang(callback.from_user.id)
    student_id = int(callback.data.split("_")[-1])

    try:
        resp = requests.get(f"{TECH_API}/student-stats/{student_id}", timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("Stats error: %s", e)
        await callback.answer(t(lang, "stats_error"), show_alert=True)
        return

    await callback.message.answer(format_stats(data, lang), parse_mode="HTML")
    await callback.answer()


# ── Unsubscribe ───────────────────────────────────────────────────────────────

@router.message(F.text.in_(["❌ Obunani bekor qilish", "❌ Отменить подписку"]))
async def unsubscribe_menu(message: types.Message):
    lang = get_lang(message.from_user.id)
    with SessionLocal() as db:
        subs = db.query(ParentSubscription).filter_by(
            telegram_id=message.from_user.id, is_active=True
        ).all()

    if not subs:
        await message.answer(t(lang, "no_active_subs"), reply_markup=main_keyboard(lang))
        return

    await message.answer(t(lang, "ask_unsub"), reply_markup=unsubscribe_keyboard(subs, lang))


@router.callback_query(F.data.startswith("unsub_"))
async def confirm_unsubscribe(callback: types.CallbackQuery):
    lang = get_lang(callback.from_user.id)
    sub_id = int(callback.data.split("_")[1])

    with SessionLocal() as db:
        sub = db.query(ParentSubscription).filter_by(
            id=sub_id, telegram_id=callback.from_user.id
        ).first()
        name = sub.student_name if sub else "O'quvchi"
        if sub:
            sub.is_active = False
            db.commit()

    await callback.message.answer(
        t(lang, "unsubbed", name=name),
        parse_mode="HTML",
        reply_markup=main_keyboard(lang)
    )
    await callback.answer()


@router.callback_query(F.data == "back_main")
async def back_to_main(callback: types.CallbackQuery):
    lang = get_lang(callback.from_user.id)
    await callback.message.answer(t(lang, "main_menu"), reply_markup=main_keyboard(lang))
    await callback.answer()


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
