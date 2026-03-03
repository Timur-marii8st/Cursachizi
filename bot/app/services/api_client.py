"""HTTP client for communicating with the CourseForge backend API."""

import httpx
import structlog

from shared.schemas.job import JobCreate, JobResponse

logger = structlog.get_logger()


class CourseForgeAPIClient:
    """Async HTTP client wrapping the CourseForge backend API."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    async def create_job(self, job: JobCreate) -> JobResponse:
        """Create a new generation job."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self._base_url}/api/jobs",
                json=job.model_dump(),
            )
            response.raise_for_status()
            return JobResponse(**response.json())

    async def get_job(self, job_id: str) -> JobResponse:
        """Get job status."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f"{self._base_url}/api/jobs/{job_id}")
            response.raise_for_status()
            return JobResponse(**response.json())

    async def cancel_job(self, job_id: str) -> JobResponse:
        """Cancel a job."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{self._base_url}/api/jobs/{job_id}/cancel"
            )
            response.raise_for_status()
            return JobResponse(**response.json())

    async def health_check(self) -> bool:
        """Check if the backend API is healthy."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._base_url}/api/health")
                return response.status_code == 200
        except httpx.HTTPError:
            return False
