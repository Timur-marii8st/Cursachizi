"""Tests for health check endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class TestHealthEndpoints:
    async def test_health_check(self, client: AsyncClient) -> None:
        response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "courseforge"

    async def test_readiness_check(self, client: AsyncClient) -> None:
        response = await client.get("/api/health/ready")
        assert response.status_code == 200
        assert response.json()["status"] == "ready"
