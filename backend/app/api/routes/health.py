"""Health check endpoints."""

from typing import Annotated

import redis.asyncio as redis
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import get_db
from backend.app.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict:
    return {"status": "ok", "service": "courseforge"}


@router.get("/health/ready", response_model=None)
async def readiness_check(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JSONResponse | dict[str, str]:
    db_ok = False
    redis_ok = False
    db_error: str | None = None
    redis_error: str | None = None

    settings = get_settings()

    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:
        db_error = str(exc) if settings.debug else "error"

    redis_pool = getattr(request.app.state, "redis_pool", None)
    if redis_pool is None:
        redis_pool = redis.from_url(settings.redis_url)
        owned = True
    else:
        owned = False

    try:
        redis_ok = bool(await redis_pool.ping())
    except Exception as exc:
        redis_error = str(exc) if settings.debug else "error"
    finally:
        if owned:
            await redis_pool.aclose()

    if not db_ok or not redis_ok:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "db": "ok" if db_ok else f"error: {db_error}",
                "redis": "ok" if redis_ok else f"error: {redis_error}",
            },
        )

    return {"status": "ready", "db": "ok", "redis": "ok"}
