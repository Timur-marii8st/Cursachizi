"""Payment API routes — Robokassa integration."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import structlog

from backend.app.api.deps import get_db, verify_internal_api_key
from backend.app.config import get_settings
from backend.app.models.payment import Payment
from backend.app.models.user import User
from backend.app.services.robokassa import (
    generate_payment_link,
    verify_result_signature,
)
from shared.schemas.payment import (
    PACKAGES_BY_ID,
    BalanceResponse,
    PaymentCreate,
    PaymentResponse,
    PaymentStatus,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post(
    "",
    response_model=PaymentResponse,
    status_code=201,
    dependencies=[Depends(verify_internal_api_key)],
)
async def create_payment(
    payment_in: PaymentCreate,
    db: AsyncSession = Depends(get_db),
) -> PaymentResponse:
    """Create a payment and return Robokassa payment URL."""
    settings = get_settings()

    if not settings.robokassa_login:
        raise HTTPException(status_code=503, detail="Payment system is not configured")

    package = PACKAGES_BY_ID.get(payment_in.package_id)
    if not package:
        raise HTTPException(status_code=400, detail="Invalid package_id")

    # Find or create user by telegram_id
    user = await _get_or_create_user_by_telegram(db, payment_in.telegram_id)

    # Create payment record
    payment = Payment(
        user_id=user.id,
        package_id=package.id,
        credits=package.credits,
        amount_rub=package.price_rub,
        status=PaymentStatus.PENDING,
    )
    db.add(payment)
    await db.flush()
    await db.refresh(payment)

    # Use payment.id as Robokassa InvId
    payment.robokassa_inv_id = payment.id

    payment_url = generate_payment_link(
        merchant_login=settings.robokassa_login,
        password1=settings.robokassa_password1,
        cost=package.price_rub,
        inv_id=payment.id,
        description=f"CourseForge: {package.label}",
        is_test=settings.robokassa_test_mode,
    )

    logger.info(
        "payment_created",
        payment_id=payment.id,
        telegram_id=payment_in.telegram_id,
        package=package.id,
        amount=package.price_rub,
    )

    return PaymentResponse(
        id=payment.id,
        user_id=user.id,
        package_id=package.id,
        credits=package.credits,
        amount_rub=package.price_rub,
        status=PaymentStatus.PENDING,
        payment_url=payment_url,
        created_at=payment.created_at,
    )


@router.post("/result", response_class=PlainTextResponse)
async def robokassa_result(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> str:
    """Robokassa ResultURL webhook — called by Robokassa when payment succeeds.

    This endpoint is public (no API key) — Robokassa needs to call it.
    Security is ensured by signature verification.
    """
    settings = get_settings()
    form = await request.form()
    out_sum = str(form.get("OutSum", ""))
    inv_id = str(form.get("InvId", ""))
    signature_value = str(form.get("SignatureValue", ""))

    if not verify_result_signature(
        password2=settings.robokassa_password2,
        out_sum=out_sum,
        inv_id=inv_id,
        signature_value=signature_value,
    ):
        logger.warning("robokassa_invalid_signature", inv_id=inv_id)
        return f"bad sign"

    # Find payment
    try:
        payment_id = int(inv_id)
    except ValueError:
        logger.warning("robokassa_invalid_inv_id", inv_id=inv_id)
        return "bad inv_id"
    payment = await db.get(Payment, payment_id)
    if not payment:
        logger.warning("robokassa_payment_not_found", inv_id=inv_id)
        return f"bad inv_id"

    if payment.status == PaymentStatus.COMPLETED:
        # Idempotent — already processed
        return f"OK{inv_id}"

    # Mark payment as completed
    payment.status = PaymentStatus.COMPLETED
    payment.completed_at = datetime.now(timezone.utc)

    # Add credits to user
    user = await db.get(User, payment.user_id)
    if user:
        user.credits_remaining += payment.credits
        logger.info(
            "credits_added",
            user_id=user.id,
            telegram_id=user.telegram_id,
            credits_added=payment.credits,
            new_balance=user.credits_remaining,
        )

    await db.flush()

    # Robokassa expects "OK{InvId}" response
    return f"OK{inv_id}"


@router.get(
    "/balance",
    response_model=BalanceResponse,
    dependencies=[Depends(verify_internal_api_key)],
)
async def get_balance(
    telegram_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
) -> BalanceResponse:
    """Get user's credit balance by Telegram ID."""
    user = await _get_user_by_telegram(db, telegram_id)
    if not user:
        # New user — return default trial balance
        return BalanceResponse(
            telegram_id=telegram_id,
            credits_remaining=1,
            total_papers_generated=0,
        )
    return BalanceResponse(
        telegram_id=telegram_id,
        credits_remaining=user.credits_remaining,
        total_papers_generated=user.total_papers_generated,
    )


async def _get_user_by_telegram(db: AsyncSession, telegram_id: int) -> User | None:
    query = select(User).where(User.telegram_id == telegram_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def _get_or_create_user_by_telegram(db: AsyncSession, telegram_id: int) -> User:
    user = await _get_user_by_telegram(db, telegram_id)
    if user:
        return user
    user = User(telegram_id=telegram_id, credits_remaining=1)
    db.add(user)
    await db.flush()
    return user
