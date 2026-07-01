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
_OVERVIEW_TEXTS = ("📊 Umumiy", "📊 Общая")
_TODAY_TEXTS = ("☀️ Bugun", "☀️ Сегодня")
_WEEKLY_TEXTS = ("📅 Hafta", "📅 Неделя")
_MONTHLY_TEXTS = ("📆 Oy", "📆 Месяц")


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
        if data.get("active_sub_id"):
            # viewing a specific child → go back to the children list
            subscriptions = data.get("subscriptions", [])
            names = [s["name"] for s in subscriptions]
            await state.update_data(
                active_sub_id=None,
                active_sub_name="",
                active_sub_id_platform=None,
            )
            await message.answer(
                t(lang, "my_children_title", n=len(names)),
                reply_markup=results_keyboard(names, lang),
            )
        else:
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

    # Period detail buttons
    if text in _OVERVIEW_TEXTS or text in _TODAY_TEXTS or text in _WEEKLY_TEXTS or text in _MONTHLY_TEXTS:
        student_id = data.get("active_sub_id_platform")
        sub_name = data.get("active_sub_name", "")
        if student_id:
            api_data = _fetch_stats(student_id)
            if api_data:
                if text in _OVERVIEW_TEXTS:
                    detail = format_stats(api_data, lang)
                elif text in _TODAY_TEXTS:
                    detail = _format_today(api_data, lang)
                elif text in _WEEKLY_TEXTS:
                    detail = _format_weekly(api_data, lang)
                else:
                    detail = _format_monthly(api_data, lang)
                await message.answer(detail, reply_markup=child_keyboard(lang))
                return
        await message.answer(t(lang, "stats_error"), reply_markup=child_keyboard(lang))
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

    # mode == "view": fetch and show stats (1 retry on failure)
    await state.update_data(
        active_sub_id=sub["sub_id"],
        active_sub_name=sub["name"],
        active_sub_id_platform=sub["student_id"],
    )
    api_data = _fetch_stats(sub["student_id"])
    stats_text = format_stats(api_data, lang) if api_data else t(lang, "stats_error")

    await message.answer(stats_text, reply_markup=child_keyboard(lang))


# ── Stats formatter ───────────────────────────────────────────────────────────

def format_stats(data: dict, lang: str) -> str:
    name = data.get("name") or "O'quvchi"
    w_ex = data.get("weekly_exercises") or {}
    text = (
        t(lang, "stats_title", name=name)
        + t(lang, "total_pts", v=data.get("total_points", 0), rank=data.get("global_rank", 0))
        + t(lang, "weekly_header")
        + t(lang, "weekly_activity",
            lessons=data.get("weekly_lessons", 0),
            correct=w_ex.get("correct", 0),
            total=w_ex.get("total", 0))
        + t(lang, "weekly_score",
            pts=data.get("weekly_points", 0),
            rank=data.get("weekly_rank", 0))
        + t(lang, "separator")
    )

    achievements = data.get("achievements", [])
    if achievements:
        badges = "  ".join(
            f"{a['icon']} {a['name']}" for a in achievements
        )
        text += t(lang, "achievements_line", badges=badges)

    status_emoji = {
        "Approved": "✅", "Submitted": "⏳", "Pending": "⏳",
        "Rejected": "❌", None: "📝", "": "📝",
    }
    status_label = {
        "uz": {"Approved": "Tasdiqlangan", "Submitted": "Tekshirilmoqda",
               "Pending": "Tekshirilmoqda", "Rejected": "Rad etilgan", None: "Topshirilmagan", "": "Topshirilmagan"},
        "ru": {"Approved": "Принято", "Submitted": "На проверке",
               "Pending": "На проверке", "Rejected": "Отклонено", None: "Не сдано", "": "Не сдано"},
    }

    for c in data.get("courses", []):
        done = c.get("lessons_completed", 0)
        total = c.get("lessons_total", 0)
        pct = round(done / total * 100) if total else 0
        ex = c.get("exercises", {})
        bar = _progress_bar(pct)

        text += f"\n📘 <b>{c['title']}</b>  {bar} {pct}%\n"
        text += t(lang, "lessons", done=done, total=total)
        text += t(lang, "exercises", correct=ex.get("correct", 0), total=ex.get("total", 0))

        projects = c.get("projects", [])
        if projects:
            counts: dict = {}
            total_pts = 0
            for p in projects:
                st = p.get("status") or None
                counts[st] = counts.get(st, 0) + 1
                if p.get("points"):
                    total_pts += p["points"]

            labels = status_label.get(lang, status_label["uz"])
            parts = []
            for st, cnt in counts.items():
                emoji = status_emoji.get(st, "📝")
                lbl = labels.get(st, st or "")
                parts.append(f"{emoji} {lbl}×{cnt}" if cnt > 1 else f"{emoji} {lbl}")
            pts_str = f" (+{total_pts} ball)" if total_pts else ""
            text += f"   🗂 {', '.join(parts)}{pts_str}\n"

    return text


def _progress_bar(pct: int) -> str:
    filled = round(pct / 10)
    return "█" * filled + "░" * (10 - filled)


def format_weekly_report(data: dict, lang: str) -> str:
    name = data.get("name") or "O'quvchi"
    w_ex = data.get("weekly_exercises") or {}

    status_emoji = {"Approved": "✅", "Submitted": "⏳", "Pending": "⏳", "Rejected": "❌", None: "📝", "": "📝"}
    status_label = {
        "uz": {"Approved": "Tasdiqlangan", "Submitted": "Tekshirilmoqda",
               "Pending": "Tekshirilmoqda", "Rejected": "Rad etilgan",
               None: "Topshirilmagan", "": "Topshirilmagan"},
        "ru": {"Approved": "Принято", "Submitted": "На проверке",
               "Pending": "На проверке", "Rejected": "Отклонено",
               None: "Не сдано", "": "Не сдано"},
    }

    text = (
        t(lang, "weekly_report_header", name=name)
        + t(lang, "weekly_report_total",
            total=data.get("total_points", 0),
            rank=data.get("global_rank", 0))
        + t(lang, "weekly_report_activity",
            lessons=data.get("weekly_lessons", 0),
            correct=w_ex.get("correct", 0),
            total=w_ex.get("total", 0),
            pts=data.get("weekly_points", 0),
            wrank=data.get("weekly_rank", 0))
        + t(lang, "separator")
    )

    # All-time project summary across all courses
    all_projects = [p for c in data.get("courses", []) for p in c.get("projects", [])]
    if all_projects:
        counts: dict = {}
        total_pts = 0
        for p in all_projects:
            st = p.get("status") or None
            counts[st] = counts.get(st, 0) + 1
            if p.get("points"):
                total_pts += p["points"]

        labels = status_label.get(lang, status_label["uz"])
        parts = []
        for st, cnt in counts.items():
            emoji = status_emoji.get(st, "📝")
            lbl = labels.get(st, st or "")
            parts.append(f"{emoji} {lbl}×{cnt}" if cnt > 1 else f"{emoji} {lbl}")
        pts_str = f"  (+{total_pts} ball)" if total_pts else ""
        text += t(lang, "weekly_report_projects") + f"   {', '.join(parts)}{pts_str}\n"
    else:
        text += t(lang, "weekly_report_no_projects")

    # Per-course exercise scores
    text += t(lang, "separator")
    for c in data.get("courses", []):
        ex = c.get("exercises", {})
        if ex.get("total", 0) > 0:
            pct = round(ex["correct"] / ex["total"] * 100)
            text += f"📘 <b>{c['title']}</b>: {ex['correct']}/{ex['total']} ✏️ ({pct}%)\n"

    return text


def format_weekly_rankings(rankings: dict, my_student_ids: list, lang: str) -> str:
    """Build a personalized weekly leaderboard message.

    Shows top 20 in each category. If a parent's child is outside top 20,
    appends their entry below a separator so parents always see their child.
    """
    ex_all = rankings.get("exercise_ranking", [])
    proj_all = rankings.get("project_ranking", [])
    my_ids = set(my_student_ids)

    def _medal(rank: int) -> str:
        return {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, "  ")

    text = t(lang, "rankings_header")

    # Exercise ranking
    text += t(lang, "rankings_ex_title")
    if not ex_all:
        text += t(lang, "rankings_no_ex")
    else:
        top20_ex_ids = set()
        for row in ex_all[:20]:
            top20_ex_ids.add(row["student_id"])
            text += t(lang, "rankings_ex_row",
                      medal=_medal(row["rank"]),
                      rank=row["rank"],
                      name=row["name"],
                      pts=row["weekly_points"])
        # Append children outside top 20
        outside = [r for r in ex_all if r["student_id"] in my_ids and r["student_id"] not in top20_ex_ids]
        if outside:
            text += t(lang, "rankings_separator")
            for row in outside:
                text += t(lang, "rankings_my_child_ex",
                          rank=row["rank"],
                          name=row["name"],
                          pts=row["weekly_points"])
        # Children with no exercises this week
        no_activity = [sid for sid in my_ids if not any(r["student_id"] == sid for r in ex_all)]
        for sid in no_activity:
            text += t(lang, "rankings_separator")
            text += t(lang, "rankings_my_child_ex", rank="—", name=f"#{sid}", pts=0)

    # Project ranking
    text += t(lang, "rankings_proj_title")
    if not proj_all:
        text += t(lang, "rankings_no_proj")
    else:
        top20_proj_ids = set()
        for row in proj_all[:20]:
            top20_proj_ids.add(row["student_id"])
            text += t(lang, "rankings_proj_row",
                      medal=_medal(row["rank"]),
                      rank=row["rank"],
                      name=row["name"],
                      approved=row["approved_count"],
                      pts=row["total_points"])
        outside = [r for r in proj_all if r["student_id"] in my_ids and r["student_id"] not in top20_proj_ids]
        if outside:
            text += t(lang, "rankings_separator")
            for row in outside:
                text += t(lang, "rankings_my_child_proj",
                          rank=row["rank"],
                          name=row["name"],
                          approved=row["approved_count"],
                          pts=row["total_points"])

    return text


def _fetch_stats(student_id: int) -> dict | None:
    for attempt in range(2):
        try:
            resp = requests.get(f"{TECH_API}/student-stats/{student_id}", timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning("Stats fetch attempt %d failed for %s: %s", attempt + 1, student_id, e)
            if attempt == 0:
                import time as _time; _time.sleep(1)
    return None


def _format_today(data: dict, lang: str) -> str:
    name = data.get("name") or "O'quvchi"
    d_ex = data.get("daily_exercises") or {}
    return (
        t(lang, "today_title", name=name)
        + t(lang, "today_pts", v=data.get("daily_points", 0))
        + t(lang, "weekly_lessons_detail", n=data.get("daily_lessons", 0))
        + t(lang, "weekly_ex_detail",
            correct=d_ex.get("correct", 0),
            total=d_ex.get("total", 0))
        + t(lang, "today_rank", v=data.get("global_rank", 0))
    )


def _format_weekly(data: dict, lang: str) -> str:
    name = data.get("name") or "O'quvchi"
    w_ex = data.get("weekly_exercises") or {}
    return (
        t(lang, "weekly_title", name=name)
        + t(lang, "weekly_lessons_detail", n=data.get("weekly_lessons", 0))
        + t(lang, "weekly_ex_detail",
            correct=w_ex.get("correct", 0),
            total=w_ex.get("total", 0))
        + t(lang, "weekly_pts_detail", v=data.get("weekly_points", 0))
        + t(lang, "weekly_rank_detail", v=data.get("weekly_rank", 0))
    )


def _format_monthly(data: dict, lang: str) -> str:
    name = data.get("name") or "O'quvchi"
    m_ex = data.get("monthly_exercises") or {}
    return (
        t(lang, "monthly_title", name=name)
        + t(lang, "monthly_pts", v=data.get("monthly_points", 0))
        + t(lang, "weekly_lessons_detail", n=data.get("monthly_lessons", 0))
        + t(lang, "weekly_ex_detail",
            correct=m_ex.get("correct", 0),
            total=m_ex.get("total", 0))
        + t(lang, "monthly_rank", v=data.get("monthly_rank", 0))
    )
