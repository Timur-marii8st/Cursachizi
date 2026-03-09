"""Tests for health check endpoints."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import get_db
from backend.app.main import app


def _db_override(*, execute_raises: Exception | None = None):
    """Return a FastAPI dependency override that yields a mock AsyncSession."""
    session = AsyncMock(spec=AsyncSession)
    if execute_raises is not None:
        session.execute.side_effect = execute_raises

    async def _override():
        yield session

    return _override


def _attach_redis(*, ping_raises: Exception | None = None) -> AsyncMock:
    """Attach a mock redis_pool to app.state and return it."""
    redis_mock = AsyncMock()
    if ping_raises is not None:
        redis_mock.ping.side_effect = ping_raises
    else:
        redis_mock.ping.return_value = True
    app.state.redis_pool = redis_mock
    return redis_mock


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestHealthCheck:
    async def test_basic_health_returns_ok(self, client: AsyncClient) -> None:
        response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "courseforge"


class TestReadinessCheck:
    async def test_ready_when_db_and_redis_succeed(self, client: AsyncClient) -> None:
        _attach_redis()
        app.dependency_overrides[get_db] = _db_override()

        try:
            response = await client.get("/api/health/ready")
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["db"] == "ok"
        assert data["redis"] == "ok"

    async def test_503_when_db_fails(self, client: AsyncClient) -> None:
        _attach_redis()
        app.dependency_overrides[get_db] = _db_override(
            execute_raises=Exception("connection refused")
        )

        try:
            response = await client.get("/api/health/ready")
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "not_ready"
        assert data["db"] != "ok"
        assert data["redis"] == "ok"

    async def test_503_when_redis_fails(self, client: AsyncClient) -> None:
        _attach_redis(ping_raises=Exception("redis unreachable"))
        app.dependency_overrides[get_db] = _db_override()

        try:
            response = await client.get("/api/health/ready")
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "not_ready"
        assert data["db"] == "ok"
        assert data["redis"] != "ok"

    async def test_503_when_both_fail(self, client: AsyncClient) -> None:
        _attach_redis(ping_raises=Exception("redis down"))
        app.dependency_overrides[get_db] = _db_override(
            execute_raises=Exception("db down")
        )

        try:
            response = await client.get("/api/health/ready")
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "not_ready"
        assert data["db"] != "ok"
        assert data["redis"] != "ok"
