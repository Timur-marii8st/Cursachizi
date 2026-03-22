"""Telegram bot entry point."""

import asyncio

import structlog
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage

from bot.app.config import get_bot_settings
from bot.app.handlers.generate import router as generate_router
from bot.app.handlers.payment import router as payment_router
from bot.app.handlers.start import router as start_router
from bot.app.handlers.status import router as status_router
from bot.app.services.api_client import CourseForgeAPIClient

logger = structlog.get_logger()


def create_bot() -> tuple[Bot, Dispatcher]:
    """Create and configure the bot and dispatcher."""
    settings = get_bot_settings()

    if not settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set")

    bot = Bot(token=settings.telegram_bot_token)

    try:
        storage = RedisStorage.from_url(settings.redis_url)
        logger.info("bot_storage", type="redis")
    except Exception as exc:
        logger.warning("bot_redis_storage_failed, falling back to memory", error=str(exc))
        storage = MemoryStorage()

    dp = Dispatcher(storage=storage)

    # Create API client and inject as middleware data
    api_client = CourseForgeAPIClient(
        base_url=settings.api_base_url,
        api_key=settings.internal_api_key,
    )
    dp["api_client"] = api_client

    # Register routers
    dp.include_router(start_router)
    dp.include_router(generate_router)
    dp.include_router(status_router)
    dp.include_router(payment_router)

    return bot, dp


async def main() -> None:
    """Start the bot in polling mode."""
    logger.info("bot_starting")
    bot, dp = create_bot()

    api_client: CourseForgeAPIClient = dp["api_client"]

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await api_client.aclose()
        await bot.session.close()
        logger.info("bot_stopped")


if __name__ == "__main__":
    asyncio.run(main())
