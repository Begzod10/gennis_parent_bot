import logging
import time
import requests
import telebot

from app.celery_app import celery
from app.config import TECH_API, BOT_TOKEN
from app.db import CelerySession
from app.i18n import t
from app.models import ParentSubscription, UserSettings
from app.handlers.start import format_stats, format_weekly_report, format_weekly_rankings

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
