"""Health check endpoints."""

import redis.asyncio as redis
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from backend.app.config import get_settings
from backend.app.db.session import async_engine

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict:
    return {"status": "ok", "service": "courseforge"}


@router.get("/health/ready")
async def readiness_check() -> dict:
    settings = get_settings()
    db_ok = False
    redis_ok = False

    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    redis_client = redis.from_url(settings.redis_url)
    try:
        redis_ok = bool(await redis_client.ping())
    except Exception:
        redis_ok = False
    finally:
        await redis_client.aclose()

    if settings.is_production and (not db_ok or not redis_ok):
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "checks": {"database": db_ok, "redis": redis_ok},
            },
        )

    return {"status": "ready", "checks": {"database": db_ok, "redis": redis_ok}}
