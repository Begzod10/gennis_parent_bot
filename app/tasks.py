import logging
import time
import requests
import telebot

from app.celery_app import celery
from app.config import TECH_API, BOT_TOKEN, INTERNAL_SECRET
from app.db import CelerySession
from app.i18n import t
from app.models import ParentSubscription, UserSettings
from app.handlers.start import format_stats, format_weekly_report, format_weekly_rankings


def _tech_api_root() -> str:
    """TECH_API is set to the /api/v1/bot prefix used by student-stats etc.
    The game-session endpoints live under /api/v1/game-sessions/ so we
    derive the API root by stripping the trailing /bot segment.
    """
    return TECH_API.rstrip("/").removesuffix("/bot")


def _fetch_session_summary(session_id: int) -> dict | None:
    """Pull the full frozen snapshot from tech_platform."""
    api_root = _tech_api_root()
    try:
        resp = requests.get(
            f"{api_root}/game-sessions/{session_id}/summary-public",
            headers={"X-Internal-Secret": INTERNAL_SECRET},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.error("Failed to fetch session summary %s: %s", session_id, exc)
        return None


def _format_session_body(lang: str, leader_row: dict, total_players: int) -> str:
    """Per-child block: rank, points, correct/wrong ratio.

    Falls back to a "no answers" line if the child never answered — team
    members who didn't participate still appear on the leaderboard with
    zero counts (per _build_snapshot_payload), so we detect that shape.
    """
    answered = leader_row.get("answered_count", 0)
    if answered == 0:
        return (
            t(lang, "gs_child_line", name=leader_row.get("full_name", "—"))
            + t(lang, "gs_no_answers")
        )
    return (
        t(lang, "gs_child_line", name=leader_row.get("full_name", "—"))
        + t(lang, "gs_rank_line", rank=leader_row.get("rank", "—"), total=total_players)
        + t(lang, "gs_score_line",
            pts=leader_row.get("total_points", 0),
            correct=leader_row.get("correct_count", 0),
            total=answered)
    )

logger = logging.getLogger(__name__)


@celery.task(name="app.tasks.send_daily_reports", bind=True, max_retries=3)
def send_daily_reports(self):
    bot = telebot.TeleBot(BOT_TOKEN)

    try:
        with CelerySession() as db:
            subscriptions = db.query(ParentSubscription).filter_by(is_active=True).all()
            lang_map = {
                u.telegram_id: u.lang
                for u in db.query(UserSettings).all()
            }
            subs_snapshot = [
                {
                    "telegram_id": s.telegram_id,
                    "student_platform_id": s.student_platform_id,
                    "student_name": s.student_name,
                    "lang": lang_map.get(s.telegram_id, "uz"),
                }
                for s in subscriptions
            ]
    except Exception as exc:
        logger.error("DB error loading subscriptions: %s", exc)
        raise self.retry(exc=exc, countdown=60)

    logger.info("Sending daily reports to %d subscriptions", len(subs_snapshot))

    for sub in subs_snapshot:
        lang = sub["lang"]
        try:
            resp = requests.get(
                f"{TECH_API}/student-stats/{sub['student_platform_id']}",
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("Failed to fetch stats for student %s: %s", sub["student_platform_id"], e)
            continue

        text = t(lang, "daily_header") + format_stats(data, lang)

        try:
            bot.send_message(sub["telegram_id"], text, parse_mode="HTML")
            logger.info("Sent report to telegram_id=%s", sub["telegram_id"])
        except Exception as e:
            logger.error("Failed to send to %s: %s", sub["telegram_id"], e)

        time.sleep(0.05)  # avoid Telegram rate limit (20 msg/sec)

    # Piggyback the daily rollup of today's completed game sessions —
    # keeps the parents' evening rhythm intact instead of a second
    # separate message. Failure here doesn't block the main daily send.
    try:
        _append_todays_game_sessions(bot, subs_snapshot)
    except Exception as exc:
        logger.error("Daily games rollup failed: %s", exc)


def _append_todays_game_sessions(bot, subs_snapshot: list[dict]) -> None:
    """Group today's game sessions by parent and send one summary each.

    Complement to the immediate per-session push in send_game_session_report:
    parents get individual pings during the day AND one evening digest so
    they can see the day at a glance. If a parent has multiple children
    who played in the same session, each child gets their own row.
    """
    if not subs_snapshot:
        return
    api_root = _tech_api_root()
    try:
        resp = requests.get(
            f"{api_root}/game-sessions/completed-today",
            headers={"X-Internal-Secret": INTERNAL_SECRET},
            timeout=10,
        )
        resp.raise_for_status()
        session_ids = [row["session_id"] for row in resp.json().get("sessions", [])]
    except Exception as exc:
        logger.error("Failed to load completed-today list: %s", exc)
        return
    if not session_ids:
        return

    # Group parents → their students, so we send one digest per parent.
    parents_by_tid: dict = {}
    for sub in subs_snapshot:
        entry = parents_by_tid.setdefault(sub["telegram_id"], {
            "lang": sub["lang"], "students": {},
        })
        entry["students"][sub["student_platform_id"]] = sub["student_name"]

    # Cache each summary once — a parent with two participating kids
    # would otherwise fetch the same session twice.
    summaries: dict = {}
    for sid in session_ids:
        summary = _fetch_session_summary(sid)
        if summary:
            summaries[sid] = summary

    for telegram_id, info in parents_by_tid.items():
        lang = info["lang"]
        student_ids = set(info["students"].keys())
        # Build per-child lines only for sessions where this parent's
        # student actually participated.
        lines_by_child: dict = {}
        for sid, summary in summaries.items():
            leaderboard = summary.get("leaderboard", [])
            total_players = len(leaderboard)
            title = (summary.get("session") or {}).get("title", "—")
            for row in leaderboard:
                stu_id = row.get("student_id")
                if stu_id not in student_ids:
                    continue
                if row.get("answered_count", 0) == 0:
                    continue
                child_name = info["students"].get(stu_id) or row.get("full_name", "—")
                lines_by_child.setdefault(child_name, []).append(
                    t(lang, "gs_daily_session_line",
                      title=title,
                      rank=row.get("rank", "—"),
                      total=total_players,
                      pts=row.get("total_points", 0))
                )
        if not lines_by_child:
            continue
        text = t(lang, "gs_daily_header")
        for child_name, lines in lines_by_child.items():
            text += t(lang, "gs_daily_child_header", name=child_name)
            text += "".join(lines)
        try:
            bot.send_message(telegram_id, text, parse_mode="HTML")
            logger.info("Sent daily games digest to telegram_id=%s (%d children, %d sessions)",
                        telegram_id, len(lines_by_child),
                        sum(len(v) for v in lines_by_child.values()))
        except Exception as exc:
            logger.error("Failed to send daily games digest to %s: %s", telegram_id, exc)
        time.sleep(0.05)


@celery.task(name="app.tasks.send_game_session_report", bind=True, max_retries=3)
def send_game_session_report(self, session_id: int):
    """Immediate per-parent notification when a game session completes.

    Triggered by the aiohttp /internal/game-session-complete route in
    main.py, which enqueues this task. Fetches the frozen snapshot from
    tech_platform, then for every leaderboard row looks up all active
    parent subscriptions and sends each parent a per-child block.
    """
    summary = _fetch_session_summary(session_id)
    if summary is None:
        raise self.retry(countdown=30)

    leaderboard = summary.get("leaderboard", [])
    session_title = (summary.get("session") or {}).get("title", "—")
    total_players = len(leaderboard)
    if not leaderboard:
        logger.info("Session %d has empty leaderboard; skipping bot push", session_id)
        return
    leader_by_student = {row["student_id"]: row for row in leaderboard}
    participant_ids = list(leader_by_student.keys())

    try:
        with CelerySession() as db:
            subs = (
                db.query(ParentSubscription)
                .filter(
                    ParentSubscription.is_active == True,  # noqa: E712
                    ParentSubscription.student_platform_id.in_(participant_ids),
                )
                .all()
            )
            lang_map = {
                u.telegram_id: u.lang
                for u in db.query(UserSettings).all()
            }
            # Snapshot parent → (lang, [(student_platform_id, student_name), …])
            parents: dict = {}
            for s in subs:
                parents.setdefault(s.telegram_id, {
                    "lang": lang_map.get(s.telegram_id, "uz"),
                    "children": [],
                })["children"].append((s.student_platform_id, s.student_name))
    except Exception as exc:
        logger.error("DB error loading subscriptions for session %d: %s", session_id, exc)
        raise self.retry(exc=exc, countdown=30)

    if not parents:
        logger.info("Session %d: no parent subscribers for its participants", session_id)
        return

    bot = telebot.TeleBot(BOT_TOKEN)
    logger.info("Session %d: pushing to %d parent(s)", session_id, len(parents))
    for telegram_id, info in parents.items():
        lang = info["lang"]
        text = (
            t(lang, "gs_header")
            + t(lang, "gs_session_title", title=session_title)
        )
        for stu_id, stu_name in info["children"]:
            row = dict(leader_by_student.get(stu_id) or {})
            if stu_name and not row.get("full_name"):
                row["full_name"] = stu_name
            text += _format_session_body(lang, row, total_players)
        try:
            bot.send_message(telegram_id, text, parse_mode="HTML")
        except Exception as exc:
            logger.error("Send failed to %s: %s", telegram_id, exc)
        time.sleep(0.05)


@celery.task(name="app.tasks.send_weekly_reports", bind=True, max_retries=3)
def send_weekly_reports(self):
    bot = telebot.TeleBot(BOT_TOKEN)

    # Load all active subscriptions grouped by parent telegram_id
    try:
        with CelerySession() as db:
            subscriptions = db.query(ParentSubscription).filter_by(is_active=True).all()
            lang_map = {
                u.telegram_id: u.lang
                for u in db.query(UserSettings).all()
            }
            # Group by parent: {telegram_id: {"lang": ..., "students": [{"id": ..., "name": ...}]}}
            parents: dict = {}
            for s in subscriptions:
                tid = s.telegram_id
                if tid not in parents:
                    parents[tid] = {
                        "lang": lang_map.get(tid, "uz"),
                        "students": [],
                    }
                parents[tid]["students"].append({
                    "id": s.student_platform_id,
                    "name": s.student_name,
                })
    except Exception as exc:
        logger.error("DB error loading subscriptions for weekly report: %s", exc)
        raise self.retry(exc=exc, countdown=60)

    # Fetch global rankings once
    try:
        resp = requests.get(f"{TECH_API}/weekly-rankings", timeout=15)
        resp.raise_for_status()
        rankings = resp.json()
    except Exception as e:
        logger.error("Failed to fetch weekly rankings: %s", e)
        rankings = {"exercise_ranking": [], "project_ranking": []}

    # Enrich ranking entries with names from subscriptions where name is missing
    name_map = {
        s.student_platform_id: s.student_name
        for s in subscriptions
    }
    for row in rankings.get("exercise_ranking", []):
        if not row.get("name") or row["name"].startswith("Student #"):
            row["name"] = name_map.get(row["student_id"], row["name"])
    for row in rankings.get("project_ranking", []):
        if not row.get("name") or row["name"].startswith("Student #"):
            row["name"] = name_map.get(row["student_id"], row["name"])

    logger.info("Sending weekly ranking reports to %d parents", len(parents))

    for telegram_id, info in parents.items():
        lang = info["lang"]
        my_ids = [s["id"] for s in info["students"]]
        text = format_weekly_rankings(rankings, my_ids, lang)
        try:
            bot.send_message(telegram_id, text, parse_mode="HTML")
            logger.info("Sent weekly ranking to telegram_id=%s", telegram_id)
        except Exception as e:
            logger.error("Failed to send weekly ranking to %s: %s", telegram_id, e)
        time.sleep(0.05)
