"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
import structlog
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app import models as _models  # noqa: F401
from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.jobs import router as jobs_router
from backend.app.api.routes.offer import router as offer_router
from backend.app.api.routes.payments import router as payments_router
from backend.app.config import get_settings
from backend.app.db.base import Base
from backend.app.db.session import async_engine

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application startup and shutdown hooks."""
    settings = get_settings()
    logger.info("app_starting", env=settings.app_env)

    # Keep local/dev startup simple while Alembic is not wired yet.
    if not settings.is_production:
        try:
            async with async_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        except Exception as exc:
            logger.warning("db_auto_init_failed", error=str(exc))

    app.state.arq_pool = None
    try:
        app.state.arq_pool = await create_pool(
            RedisSettings.from_dsn(settings.redis_url)
        )
    except Exception as exc:
        logger.warning("arq_pool_init_failed", error=str(exc))

    app.state.redis_pool = None
    try:
        app.state.redis_pool = aioredis.from_url(
            settings.redis_url, decode_responses=True
        )
    except Exception as exc:
        logger.warning("redis_pool_init_failed", error=str(exc))

    yield

    redis_pool = getattr(app.state, "redis_pool", None)
    if redis_pool is not None:
        await redis_pool.aclose()

    arq_pool = getattr(app.state, "arq_pool", None)
    if arq_pool is not None:
        await arq_pool.close()

    logger.info("app_shutting_down")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="CourseForge API",
        description="AI-powered coursework generation platform",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
    )

    # CORS — REFACT-006: don't combine allow_origins=["*"] with allow_credentials=True
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.debug else [],
        allow_credentials=not settings.debug,  # credentials only with explicit origins
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routes
    app.include_router(health_router, prefix="/api")
    app.include_router(jobs_router, prefix="/api")
    app.include_router(payments_router, prefix="/api")
    app.include_router(offer_router, prefix="/api")

    return app


app = create_app()
