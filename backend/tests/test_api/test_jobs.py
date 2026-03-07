"""Tests for job management API routes."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.api.deps import (
    enforce_job_rate_limit,
    get_db,
    verify_internal_api_key,
)
from backend.app.main import app
from shared.schemas.job import JobStage, JobStatus


def _make_mock_job(**overrides):
    """Create a mock Job ORM object."""
    job_id = overrides.get("id", str(uuid4()))
    defaults = {
        "id": job_id,
        "user_id": str(uuid4()),
        "topic": "Влияние цифровизации на управление персоналом",
        "university": "МГУ",
        "discipline": "Менеджмент",
        "page_count": 30,
        "language": "ru",
        "template_id": None,
        "additional_instructions": "",
        "work_type": "coursework",
        "reference_s3_key": None,
        "status": JobStatus.PENDING,
        "stage": JobStage.QUEUED,
        "progress_pct": 0,
        "stage_message": "",
        "document_url": None,
        "error_message": None,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "completed_at": None,
    }
    defaults.update(overrides)
    job = MagicMock()
    for k, v in defaults.items():
        setattr(job, k, v)
    return job


def _make_mock_user():
    user = MagicMock()
    user.id = str(uuid4())
    user.username = "default"
    user.first_name = "Default"
    user.last_name = "User"
    return user


@pytest.fixture
def sample_job():
    return _make_mock_job()


@pytest.fixture
def mock_db(sample_job):
    """Create a mock async DB session."""
    session = AsyncMock()
    session.get = AsyncMock(return_value=sample_job)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    # refresh should populate missing fields on newly added Job objects
    async def _refresh(obj, *args, **kwargs):
        if not hasattr(obj, "_refreshed"):
            if getattr(obj, "id", None) is None:
                obj.id = str(uuid4())
            if getattr(obj, "created_at", None) is None:
                obj.created_at = datetime.utcnow()
            if getattr(obj, "updated_at", None) is None:
                obj.updated_at = datetime.utcnow()
            obj._refreshed = True

    session.refresh = AsyncMock(side_effect=_refresh)

    mock_user = _make_mock_user()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_user
    mock_result.scalars.return_value.all.return_value = [sample_job]
    session.execute = AsyncMock(return_value=mock_result)

    return session


@pytest.fixture
def mock_arq_pool():
    pool = AsyncMock()
    pool.enqueue_job = AsyncMock()
    return pool


@pytest.fixture
async def client(mock_db, mock_arq_pool):
    """Create test client with overridden dependencies."""

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[verify_internal_api_key] = lambda: None
    app.dependency_overrides[enforce_job_rate_limit] = lambda: None

    app.state.arq_pool = mock_arq_pool

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()


class TestCreateJob:
    async def test_create_job_success(
        self, client: AsyncClient, mock_arq_pool
    ) -> None:
        response = await client.post(
            "/api/jobs",
            json={
                "topic": "Влияние цифровизации на HR",
                "university": "МГУ",
                "discipline": "Менеджмент",
                "page_count": 30,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "pending"

    async def test_create_job_minimal(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/jobs",
            json={"topic": "Минимальная тема для теста"},
        )
        assert response.status_code == 201

    async def test_create_job_topic_too_short(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/jobs",
            json={"topic": "Аб"},
        )
        assert response.status_code == 422

    async def test_create_job_invalid_page_count(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/jobs",
            json={"topic": "Валидная тема для курсовой", "page_count": 3},
        )
        assert response.status_code == 422


class TestGetJob:
    async def test_get_job_success(
        self, client: AsyncClient, sample_job
    ) -> None:
        response = await client.get(f"/api/jobs/{sample_job.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == sample_job.id
        assert data["status"] == "pending"

    async def test_get_job_not_found(
        self, client: AsyncClient, mock_db
    ) -> None:
        mock_db.get = AsyncMock(return_value=None)
        response = await client.get(f"/api/jobs/{uuid4()}")
        assert response.status_code == 404

    async def test_get_running_job_has_progress(
        self, client: AsyncClient, sample_job
    ) -> None:
        sample_job.status = JobStatus.RUNNING
        sample_job.stage = JobStage.WRITING
        sample_job.progress_pct = 45
        sample_job.stage_message = "Написание главы 2"

        response = await client.get(f"/api/jobs/{sample_job.id}")
        data = response.json()
        assert data["status"] == "running"
        assert data["progress"]["stage"] == "writing"
        assert data["progress"]["progress_pct"] == 45


class TestListJobs:
    async def test_list_jobs(self, client: AsyncClient) -> None:
        response = await client.get("/api/jobs")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    async def test_list_jobs_with_params(self, client: AsyncClient) -> None:
        response = await client.get("/api/jobs?limit=5&offset=0")
        assert response.status_code == 200


class TestCancelJob:
    async def test_cancel_pending_job(
        self, client: AsyncClient, sample_job
    ) -> None:
        response = await client.post(f"/api/jobs/{sample_job.id}/cancel")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "cancelled"

    async def test_cancel_running_job(
        self, client: AsyncClient, sample_job
    ) -> None:
        sample_job.status = JobStatus.RUNNING
        response = await client.post(f"/api/jobs/{sample_job.id}/cancel")
        assert response.status_code == 200

    async def test_cancel_completed_job_fails(
        self, client: AsyncClient, sample_job
    ) -> None:
        sample_job.status = JobStatus.COMPLETED
        response = await client.post(f"/api/jobs/{sample_job.id}/cancel")
        assert response.status_code == 400

    async def test_cancel_nonexistent_job(
        self, client: AsyncClient, mock_db
    ) -> None:
        mock_db.get = AsyncMock(return_value=None)
        response = await client.post(f"/api/jobs/{uuid4()}/cancel")
        assert response.status_code == 404


class TestApiKeyEnforcement:
    async def test_no_key_when_required(self, mock_db, mock_arq_pool) -> None:
        """When INTERNAL_API_KEY is set, requests without key should fail."""
        app.dependency_overrides.pop(verify_internal_api_key, None)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[enforce_job_rate_limit] = lambda: None
        app.state.arq_pool = mock_arq_pool

        with patch(
            "backend.app.api.deps.get_settings"
        ) as mock_settings:
            settings = MagicMock()
            settings.internal_api_key = "secret-key-123"
            mock_settings.return_value = settings

            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as c:
                response = await c.get("/api/jobs")
                assert response.status_code == 401

        app.dependency_overrides.clear()

    async def test_correct_key_accepted(self, mock_db, mock_arq_pool) -> None:
        """When correct key is provided, request should succeed."""
        app.dependency_overrides.pop(verify_internal_api_key, None)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[enforce_job_rate_limit] = lambda: None
        app.state.arq_pool = mock_arq_pool

        with patch(
            "backend.app.api.deps.get_settings"
        ) as mock_settings:
            settings = MagicMock()
            settings.internal_api_key = "secret-key-123"
            mock_settings.return_value = settings

            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as c:
                response = await c.get(
                    "/api/jobs",
                    headers={"X-API-Key": "secret-key-123"},
                )
                assert response.status_code == 200

        app.dependency_overrides.clear()
