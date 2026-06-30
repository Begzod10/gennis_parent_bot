from celery import Celery
from celery.schedules import crontab
from app.config import CELERY_BROKER_URL, CELERY_RESULT_BACKEND

celery = Celery("gennis_parent_bot", broker=CELERY_BROKER_URL, backend=CELERY_RESULT_BACKEND)

celery.conf.timezone = "Asia/Tashkent"
celery.conf.beat_schedule = {
    "send-daily-parent-reports": {
        "task": "app.tasks.send_daily_reports",
        "schedule": crontab(hour=20, minute=0),
    },
}

from app import tasks  # noqa: E402, F401
