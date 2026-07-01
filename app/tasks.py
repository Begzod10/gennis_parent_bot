import logging
import time
import requests
import telebot

from app.celery_app import celery
from app.config import TECH_API, BOT_TOKEN
from app.db import CelerySession
from app.i18n import t
from app.models import ParentSubscription, UserSettings
from app.handlers.start import format_stats, format_weekly_report

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
        logger.error("DB error loading subscriptions for weekly report: %s", exc)
        raise self.retry(exc=exc, countdown=60)

    logger.info("Sending weekly reports to %d subscriptions", len(subs_snapshot))

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

        text = format_weekly_report(data, lang)

        try:
            bot.send_message(sub["telegram_id"], text, parse_mode="HTML")
            logger.info("Sent weekly report to telegram_id=%s", sub["telegram_id"])
        except Exception as e:
            logger.error("Failed to send weekly to %s: %s", sub["telegram_id"], e)

        time.sleep(0.05)
