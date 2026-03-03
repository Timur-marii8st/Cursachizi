"""Health check endpoints."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict:
    return {"status": "ok", "service": "courseforge"}


@router.get("/health/ready")
async def readiness_check() -> dict:
    # TODO: Check DB and Redis connectivity in production
    return {"status": "ready"}
