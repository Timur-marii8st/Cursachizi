"""Tests for payment API routes — create payment, webhook, balance."""

import hashlib
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.api.deps import get_db, verify_internal_api_key
from backend.app.main import app
from shared.schemas.payment import PaymentStatus


def _make_mock_user(**overrides):
    user = MagicMock()
    defaults = {
        "id": str(uuid4()),
        "telegram_id": 123456789,
        "username": None,
        "first_name": "",
        "last_name": "",
        "credits_remaining": 1,
        "total_papers_generated": 0,
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(user, k, v)
    return user


def _make_mock_payment(**overrides):
    payment = MagicMock()
    defaults = {
        "id": 42,
        "user_id": str(uuid4()),
        "package_id": "pack_1",
        "credits": 1,
        "amount_rub": 199,
        "status": PaymentStatus.PENDING,
        "robokassa_inv_id": 42,
        "created_at": datetime.utcnow(),
        "completed_at": None,
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(payment, k, v)
    return payment


@pytest.fixture
def mock_user():
    return _make_mock_user()


@pytest.fixture
def mock_payment(mock_user):
    return _make_mock_payment(user_id=mock_user.id)


@pytest.fixture
def mock_db(mock_user, mock_payment):
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    # db.get returns payment or user based on model type
    async def _get(model, pk):
        from backend.app.models.payment import Payment
        from backend.app.models.user import User

        if model is Payment:
            return mock_payment
        if model is User:
            return mock_user
        return None

    session.get = AsyncMock(side_effect=_get)

    # refresh populates id/created_at on new objects
    async def _refresh(obj, *args, **kwargs):
        if getattr(obj, "id", None) is None:
            obj.id = 42
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.utcnow()

    session.refresh = AsyncMock(side_effect=_refresh)

    # execute returns user for select queries
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_user
    session.execute = AsyncMock(return_value=mock_result)

    return session


@pytest.fixture
def mock_settings():
    settings = MagicMock()
    settings.robokassa_login = "TestShop"
    settings.robokassa_password1 = "pass1"
    settings.robokassa_password2 = "pass2"
    settings.robokassa_test_mode = True
    return settings


@pytest.fixture
async def client(mock_db):
    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[verify_internal_api_key] = lambda: None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()


class TestCreatePayment:
    async def test_create_payment_success(
        self, client: AsyncClient, mock_settings
    ) -> None:
        with patch("backend.app.api.routes.payments.get_settings", return_value=mock_settings):
            response = await client.post(
                "/api/payments",
                json={"package_id": "pack_1", "telegram_id": 123456789},
            )
        assert response.status_code == 201
        data = response.json()
        assert data["package_id"] == "pack_1"
        assert data["credits"] == 1
        assert data["amount_rub"] == 199
        assert data["status"] == "pending"
        assert data["payment_url"] is not None
        assert "robokassa.ru" in data["payment_url"]

    async def test_create_payment_invalid_package(
        self, client: AsyncClient, mock_settings
    ) -> None:
        with patch("backend.app.api.routes.payments.get_settings", return_value=mock_settings):
            response = await client.post(
                "/api/payments",
                json={"package_id": "nonexistent", "telegram_id": 123},
            )
        assert response.status_code == 400
        assert "Invalid package_id" in response.json()["detail"]

    async def test_create_payment_robokassa_not_configured(
        self, client: AsyncClient
    ) -> None:
        settings = MagicMock()
        settings.robokassa_login = ""
        with patch("backend.app.api.routes.payments.get_settings", return_value=settings):
            response = await client.post(
                "/api/payments",
                json={"package_id": "pack_1", "telegram_id": 123},
            )
        assert response.status_code == 503

    async def test_create_payment_pack_3(
        self, client: AsyncClient, mock_settings
    ) -> None:
        with patch("backend.app.api.routes.payments.get_settings", return_value=mock_settings):
            response = await client.post(
                "/api/payments",
                json={"package_id": "pack_3", "telegram_id": 999},
            )
        assert response.status_code == 201
        data = response.json()
        assert data["credits"] == 3
        assert data["amount_rub"] == 549

    async def test_create_payment_missing_telegram_id(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            "/api/payments",
            json={"package_id": "pack_1"},
        )
        assert response.status_code == 422


class TestRobokassaWebhook:
    def _make_signature(self, out_sum: str, inv_id: str, password2: str) -> str:
        return hashlib.md5(f"{out_sum}:{inv_id}:{password2}".encode()).hexdigest()

    async def test_valid_webhook(
        self, client: AsyncClient, mock_settings, mock_payment, mock_user
    ) -> None:
        sig = self._make_signature("199", "42", "pass2")
        with patch("backend.app.api.routes.payments.get_settings", return_value=mock_settings):
            response = await client.post(
                "/api/payments/result",
                data={"OutSum": "199", "InvId": "42", "SignatureValue": sig},
            )
        assert response.status_code == 200
        assert response.text == "OK42"
        # Verify credits were added
        assert mock_user.credits_remaining == 1 + mock_payment.credits

    async def test_invalid_signature(
        self, client: AsyncClient, mock_settings
    ) -> None:
        with patch("backend.app.api.routes.payments.get_settings", return_value=mock_settings):
            response = await client.post(
                "/api/payments/result",
                data={"OutSum": "199", "InvId": "42", "SignatureValue": "bad_sig"},
            )
        assert response.status_code == 200
        assert response.text == "bad sign"

    async def test_payment_not_found(
        self, client: AsyncClient, mock_settings, mock_db
    ) -> None:
        # Override db.get to return None for Payment
        original_get = mock_db.get.side_effect

        async def _get_none(model, pk):
            from backend.app.models.payment import Payment

            if model is Payment:
                return None
            return await original_get(model, pk) if original_get else None

        mock_db.get = AsyncMock(side_effect=_get_none)

        sig = self._make_signature("199", "42", "pass2")
        with patch("backend.app.api.routes.payments.get_settings", return_value=mock_settings):
            response = await client.post(
                "/api/payments/result",
                data={"OutSum": "199", "InvId": "42", "SignatureValue": sig},
            )
        assert response.text == "bad inv_id"

    async def test_idempotent_completed_payment(
        self, client: AsyncClient, mock_settings, mock_payment
    ) -> None:
        mock_payment.status = PaymentStatus.COMPLETED
        sig = self._make_signature("199", "42", "pass2")
        with patch("backend.app.api.routes.payments.get_settings", return_value=mock_settings):
            response = await client.post(
                "/api/payments/result",
                data={"OutSum": "199", "InvId": "42", "SignatureValue": sig},
            )
        assert response.text == "OK42"


class TestGetBalance:
    async def test_existing_user(self, client: AsyncClient, mock_user) -> None:
        mock_user.credits_remaining = 5
        mock_user.total_papers_generated = 3
        response = await client.get(
            "/api/payments/balance",
            params={"telegram_id": mock_user.telegram_id},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["credits_remaining"] == 5
        assert data["total_papers_generated"] == 3

    async def test_new_user_default_balance(
        self, client: AsyncClient, mock_db
    ) -> None:
        # No user found
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.get(
            "/api/payments/balance",
            params={"telegram_id": 999999},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["credits_remaining"] == 1
        assert data["total_papers_generated"] == 0

    async def test_missing_telegram_id_param(self, client: AsyncClient) -> None:
        response = await client.get("/api/payments/balance")
        assert response.status_code == 422
