import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError
from aiogram.fsm.storage.redis import RedisStorage

from app.config import BOT_TOKEN
from app.handlers.start import router as start_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def main():
    session = AiohttpSession(timeout=60)
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=session,
    )
    storage = RedisStorage.from_url("redis://localhost:6379/3")
    dp = Dispatcher(storage=storage)
    dp.include_router(start_router)

    while True:
        try:
            logger.info("Gennis Parent Bot started")
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        except TelegramNetworkError as e:
            logger.warning("Network error, retrying in 5s: %s", e)
            await asyncio.sleep(5)
        except Exception as e:
            logger.error("Unexpected error, retrying in 10s: %s", e)
            await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())
