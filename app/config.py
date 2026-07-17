import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
TECH_API = os.getenv("TECH_API", "https://tech.gennis.uz/api/v1/bot")
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/3")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/3")

# Shared secret with tech_platform. Used both when tech_platform POSTs to
# /internal/game-session-complete on this bot and when this bot's celery
# tasks pull summary data back from tech_platform's *-public endpoints.
INTERNAL_SECRET = os.getenv("INTERNAL_SECRET", "")
