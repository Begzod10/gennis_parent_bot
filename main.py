import json
import logging
from typing import Optional

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.methods.base import TelegramMethod
from aiogram.types import Update

from app.config import BOT_TOKEN
from app.handlers.start import router as start_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

WEBHOOK_PATH = "/parent-webhook"
WEBAPP_PORT = 8064


class InlineSession(AiohttpSession):
    """Captures the first bot method call to return inline in the webhook response.

    Subclasses AiohttpSession (concrete) to avoid abstract-method errors.
    Overrides make_request so no outbound connection to api.telegram.org is made.
    """

    def __init__(self) -> None:
        super().__init__()
        self.captured: Optional[TelegramMethod] = None

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout=None):
        if self.captured is None:
            self.captured = method
        return None

    async def close(self) -> None:
        pass


def _method_to_dict(method: TelegramMethod) -> dict:
    cls_name = type(method).__name__
    api_method_name = cls_name[0].lower() + cls_name[1:]
    data = json.loads(method.model_dump_json(exclude_none=True, by_alias=True))
    data["method"] = api_method_name
    return data


storage = RedisStorage.from_url("redis://localhost:6379/3")
dp = Dispatcher(storage=storage)
dp.include_router(start_router)


async def webhook_handler(request: web.Request) -> web.Response:
    try:
        update_data = await request.json()
    except Exception:
        return web.Response(status=400)

    session = InlineSession()
    bot = Bot(
        token=BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        update = Update.model_validate(update_data)
        await dp.feed_update(bot, update)
    except Exception:
        logger.exception("Error processing update_id=%s", update_data.get("update_id"))

    if session.captured is not None:
        return web.json_response(_method_to_dict(session.captured))
    return web.json_response({})


def main() -> None:
    app = web.Application()
    app.router.add_post(WEBHOOK_PATH, webhook_handler)
    logger.info("Webhook server running on port %d at %s", WEBAPP_PORT, WEBHOOK_PATH)
    web.run_app(app, host="127.0.0.1", port=WEBAPP_PORT, print=None)


if __name__ == "__main__":
    main()
