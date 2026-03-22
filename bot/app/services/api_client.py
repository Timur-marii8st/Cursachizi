"""HTTP client for communicating with the CourseForge backend API.

ARCH-003: Uses a persistent httpx.AsyncClient to reuse TCP/TLS connections
across requests instead of creating a new client per call.
"""

import httpx
import structlog

from shared.schemas.job import JobCreate, JobResponse
from shared.schemas.payment import BalanceResponse, PaymentCreate, PaymentResponse

logger = structlog.get_logger()


class CourseForgeAPIClient:
    """Async HTTP client wrapping the CourseForge backend API.

    Uses a persistent httpx.AsyncClient for connection pooling.
    Call aclose() when done (e.g. during bot shutdown).
    """

    def __init__(self, base_url: str, api_key: str = "") -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key.strip()
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=30.0,
            headers=self._build_headers(),
        )

    def _build_headers(self) -> dict[str, str]:
        if not self._api_key:
            return {}
        return {"X-API-Key": self._api_key}

    async def aclose(self) -> None:
        """Close the underlying httpx client."""
        await self._client.aclose()

    async def create_job(self, job: JobCreate) -> JobResponse:
        """Create a new generation job."""
        response = await self._client.post(
            "/api/jobs",
            json=job.model_dump(),
        )
        response.raise_for_status()
        return JobResponse(**response.json())

    async def get_job(self, job_id: str) -> JobResponse:
        """Get job status."""
        response = await self._client.get(f"/api/jobs/{job_id}")
        response.raise_for_status()
        return JobResponse(**response.json())

    async def list_jobs(
        self, telegram_id: int, limit: int = 20, offset: int = 0
    ) -> list[JobResponse]:
        """List jobs from the backend API."""
        response = await self._client.get(
            "/api/jobs",
            params={"telegram_id": telegram_id, "limit": limit, "offset": offset},
        )
        response.raise_for_status()
        return [JobResponse(**item) for item in response.json()]

    async def cancel_job(self, job_id: str) -> JobResponse:
        """Cancel a job."""
        response = await self._client.post(f"/api/jobs/{job_id}/cancel")
        response.raise_for_status()
        return JobResponse(**response.json())

    async def create_payment(self, payment: PaymentCreate) -> PaymentResponse:
        """Create a payment and get Robokassa URL."""
        response = await self._client.post(
            "/api/payments",
            json=payment.model_dump(),
        )
        response.raise_for_status()
        return PaymentResponse(**response.json())

    async def get_balance(self, telegram_id: int) -> BalanceResponse:
        """Get user's credit balance."""
        response = await self._client.get(
            "/api/payments/balance",
            params={"telegram_id": telegram_id},
        )
        response.raise_for_status()
        return BalanceResponse(**response.json())

    async def download_document(self, job_id: str) -> bytes:
        """Download generated .docx bytes for a completed job."""
        response = await self._client.get(
            f"/api/jobs/{job_id}/download",
            timeout=120.0,
        )
        response.raise_for_status()
        return response.content

    async def health_check(self) -> bool:
        """Check if the backend API is healthy."""
        try:
            response = await self._client.get("/api/health", timeout=5.0)
            return response.status_code == 200
        except httpx.HTTPError:
            return False
