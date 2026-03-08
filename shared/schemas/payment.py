"""Payment-related schemas shared between backend and bot."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class PaymentStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class CreditPackage(BaseModel):
    """A purchasable credit package."""

    id: str
    credits: int
    price_rub: int
    price_per_credit: int
    label: str


# Fixed pricing: 1 credit = 199 RUB, bulk discounts
CREDIT_PACKAGES: list[CreditPackage] = [
    CreditPackage(
        id="pack_1", credits=1, price_rub=199, price_per_credit=199, label="1 кредит",
    ),
    CreditPackage(
        id="pack_3", credits=3, price_rub=549, price_per_credit=183, label="3 кредита",
    ),
    CreditPackage(
        id="pack_5", credits=5, price_rub=849, price_per_credit=170, label="5 кредитов",
    ),
    CreditPackage(
        id="pack_10", credits=10, price_rub=1490, price_per_credit=149, label="10 кредитов",
    ),
]

PACKAGES_BY_ID: dict[str, CreditPackage] = {p.id: p for p in CREDIT_PACKAGES}


class PaymentCreate(BaseModel):
    """Request to create a payment."""

    package_id: str = Field(..., description="Credit package ID (pack_1, pack_3, pack_5, pack_10)")
    telegram_id: int = Field(..., description="Telegram user ID")


class PaymentResponse(BaseModel):
    """Payment info returned from API."""

    id: int
    user_id: str
    package_id: str
    credits: int
    amount_rub: int
    status: PaymentStatus
    payment_url: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class BalanceResponse(BaseModel):
    """User's current credit balance."""

    telegram_id: int
    credits_remaining: int
    total_papers_generated: int
