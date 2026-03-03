"""Tests for the CourseForge API client."""

import pytest
import httpx
import respx

from bot.app.services.api_client import CourseForgeAPIClient
from shared.schemas.job import JobCreate, JobStatus


@pytest.fixture
def api_client() -> CourseForgeAPIClient:
    return CourseForgeAPIClient(base_url="http://test-api:8000")


class TestCourseForgeAPIClient:
    @respx.mock
    async def test_create_job(self, api_client: CourseForgeAPIClient) -> None:
        respx.post("http://test-api:8000/api/jobs").mock(
            return_value=httpx.Response(
                201,
                json={
                    "id": "test-job-id",
                    "status": "pending",
                    "topic": "Test topic",
                    "university": "",
                    "discipline": "",
                    "page_count": 30,
                    "language": "ru",
                    "template_id": None,
                    "progress": None,
                    "document_url": None,
                    "error_message": None,
                    "created_at": "2025-01-01T00:00:00Z",
                    "updated_at": "2025-01-01T00:00:00Z",
                    "completed_at": None,
                },
            )
        )

        job = await api_client.create_job(
            JobCreate(topic="Test topic")
        )

        assert job.id == "test-job-id"
        assert job.status == JobStatus.PENDING
        assert job.topic == "Test topic"

    @respx.mock
    async def test_get_job(self, api_client: CourseForgeAPIClient) -> None:
        respx.get("http://test-api:8000/api/jobs/abc123").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "abc123",
                    "status": "running",
                    "topic": "Running job",
                    "university": "",
                    "discipline": "",
                    "page_count": 25,
                    "language": "ru",
                    "template_id": None,
                    "progress": {
                        "stage": "writing",
                        "progress_pct": 50,
                        "message": "Writing sections",
                        "sources_found": 0,
                        "sections_written": 0,
                        "sections_total": 0,
                        "claims_checked": 0,
                    },
                    "document_url": None,
                    "error_message": None,
                    "created_at": "2025-01-01T00:00:00Z",
                    "updated_at": "2025-01-01T00:00:00Z",
                    "completed_at": None,
                },
            )
        )

        job = await api_client.get_job("abc123")
        assert job.id == "abc123"
        assert job.status == JobStatus.RUNNING
        assert job.progress is not None
        assert job.progress.progress_pct == 50

    @respx.mock
    async def test_health_check_success(self, api_client: CourseForgeAPIClient) -> None:
        respx.get("http://test-api:8000/api/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )

        result = await api_client.health_check()
        assert result is True

    @respx.mock
    async def test_health_check_failure(self, api_client: CourseForgeAPIClient) -> None:
        respx.get("http://test-api:8000/api/health").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        result = await api_client.health_check()
        assert result is False
