import json
import logging
from enum import Enum
from typing import Optional

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import Default as AiogramDefault, DefaultBotProperties
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


class _TelegramEncoder(json.JSONEncoder):
    """Resolves aiogram Default sentinels and Enum values during JSON serialization."""

    _DEFAULTS = {"parse_mode": ParseMode.HTML.value}

    def default(self, obj):
        if isinstance(obj, AiogramDefault):
            return self._DEFAULTS.get(obj.name)
        if isinstance(obj, Enum):
            return obj.value
        return super().default(obj)


def _strip_nulls(obj):
    """Recursively remove None/null from dicts and lists."""
    if isinstance(obj, dict):
        return {k: _strip_nulls(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_strip_nulls(item) for item in obj]
    return obj


def _method_to_dict(method: TelegramMethod) -> dict:
    raw = method.model_dump(mode="python", by_alias=True)
    json_str = json.dumps(raw, cls=_TelegramEncoder)
    data = _strip_nulls(json.loads(json_str))
    cls_name = type(method).__name__
    data["method"] = cls_name[0].lower() + cls_name[1:]
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
        try:
            result = _method_to_dict(session.captured)
            logger.info("Inline response: method=%s chat_id=%s", result.get("method"), result.get("chat_id"))
            return web.json_response(result)
        except Exception:
            logger.exception("Failed to serialize captured method %s", type(session.captured).__name__)
    else:
        logger.warning("No method captured for update_id=%s", update_data.get("update_id"))

    return web.json_response({})


def main() -> None:
    app = web.Application()
    app.router.add_post(WEBHOOK_PATH, webhook_handler)
    logger.info("Webhook server running on port %d at %s", WEBAPP_PORT, WEBHOOK_PATH)
    web.run_app(app, host="127.0.0.1", port=WEBAPP_PORT, print=None)


if __name__ == "__main__":
    main()
