"""HTTP client for communicating with the CourseForge backend API."""

import httpx
import structlog

from shared.schemas.job import JobCreate, JobResponse
from shared.schemas.payment import BalanceResponse, PaymentCreate, PaymentResponse

logger = structlog.get_logger()


class CourseForgeAPIClient:
    """Async HTTP client wrapping the CourseForge backend API."""

    def __init__(self, base_url: str, api_key: str = "") -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key.strip()

    def _headers(self) -> dict[str, str]:
        if not self._api_key:
            return {}
        return {"X-API-Key": self._api_key}

    async def create_job(self, job: JobCreate) -> JobResponse:
        """Create a new generation job."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self._base_url}/api/jobs",
                json=job.model_dump(),
                headers=self._headers(),
            )
            response.raise_for_status()
            return JobResponse(**response.json())

    async def get_job(self, job_id: str) -> JobResponse:
        """Get job status."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{self._base_url}/api/jobs/{job_id}",
                headers=self._headers(),
            )
            response.raise_for_status()
            return JobResponse(**response.json())

    async def list_jobs(self, limit: int = 20, offset: int = 0) -> list[JobResponse]:
        """List jobs from the backend API."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{self._base_url}/api/jobs",
                params={"limit": limit, "offset": offset},
                headers=self._headers(),
            )
            response.raise_for_status()
            return [JobResponse(**item) for item in response.json()]

    async def cancel_job(self, job_id: str) -> JobResponse:
        """Cancel a job."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{self._base_url}/api/jobs/{job_id}/cancel",
                headers=self._headers(),
            )
            response.raise_for_status()
            return JobResponse(**response.json())

    async def create_payment(self, payment: PaymentCreate) -> PaymentResponse:
        """Create a payment and get Robokassa URL."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self._base_url}/api/payments",
                json=payment.model_dump(),
                headers=self._headers(),
            )
            response.raise_for_status()
            return PaymentResponse(**response.json())

    async def get_balance(self, telegram_id: int) -> BalanceResponse:
        """Get user's credit balance."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{self._base_url}/api/payments/balance",
                params={"telegram_id": telegram_id},
                headers=self._headers(),
            )
            response.raise_for_status()
            return BalanceResponse(**response.json())

    async def health_check(self) -> bool:
        """Check if the backend API is healthy."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._base_url}/api/health")
                return response.status_code == 200
        except httpx.HTTPError:
            return False
