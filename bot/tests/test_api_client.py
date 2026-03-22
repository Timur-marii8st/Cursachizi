"""Tests for the CourseForge API client."""

import json

import httpx
import pytest
import respx

from bot.app.services.api_client import CourseForgeAPIClient
from shared.schemas.job import JobCreate, JobStatus, WorkType


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
                    "work_type": "coursework",
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
    async def test_create_article_job(self, api_client: CourseForgeAPIClient) -> None:
        route = respx.post("http://test-api:8000/api/jobs").mock(
            return_value=httpx.Response(
                201,
                json={
                    "id": "article-job-id",
                    "status": "pending",
                    "work_type": "article",
                    "topic": "Article topic",
                    "university": "",
                    "discipline": "",
                    "page_count": 10,
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
            JobCreate(topic="Article topic", work_type=WorkType.ARTICLE, page_count=10)
        )

        assert job.id == "article-job-id"
        assert job.status == JobStatus.PENDING
        assert job.work_type == WorkType.ARTICLE

        sent_body = json.loads(route.calls.last.request.content)
        assert sent_body["work_type"] == "article"

    @respx.mock
    async def test_get_job(self, api_client: CourseForgeAPIClient) -> None:
        respx.get("http://test-api:8000/api/jobs/abc123").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "abc123",
                    "status": "running",
                    "work_type": "coursework",
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

    @respx.mock
    async def test_list_jobs(self, api_client: CourseForgeAPIClient) -> None:
        respx.get("http://test-api:8000/api/jobs").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": "abc123",
                        "status": "completed",
                        "work_type": "coursework",
                        "topic": "Done job",
                        "university": "",
                        "discipline": "",
                        "page_count": 25,
                        "language": "ru",
                        "template_id": None,
                        "progress": None,
                        "document_url": "https://example.com/doc.docx",
                        "error_message": None,
                        "created_at": "2025-01-01T00:00:00Z",
                        "updated_at": "2025-01-01T00:00:00Z",
                        "completed_at": "2025-01-01T00:05:00Z",
                    }
                ],
            )
        )

        jobs = await api_client.list_jobs(telegram_id=12345, limit=1)
        assert len(jobs) == 1
        assert jobs[0].id == "abc123"
        assert jobs[0].status == JobStatus.COMPLETED
