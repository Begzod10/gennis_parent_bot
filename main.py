import logging

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from app.config import BOT_TOKEN
from app.handlers.start import router as start_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

WEBHOOK_PATH = "/parent-webhook"
WEBAPP_PORT = 8064


def main():
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    storage = RedisStorage.from_url("redis://localhost:6379/3")
    dp = Dispatcher(storage=storage)
    dp.include_router(start_router)

    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    logger.info("Webhook server running on port %d at %s", WEBAPP_PORT, WEBHOOK_PATH)
    web.run_app(app, host="127.0.0.1", port=WEBAPP_PORT, print=None)


if __name__ == "__main__":
    main()
