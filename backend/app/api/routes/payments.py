"""Payment API routes — Robokassa integration."""

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import get_db, verify_internal_api_key
from backend.app.config import get_settings
from backend.app.models.payment import Payment
from backend.app.models.user import User
from backend.app.services.robokassa import (
    generate_payment_link,
    verify_result_signature,
)
from backend.app.services.user_service import get_or_create_user_by_telegram_id
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
    user = await get_or_create_user_by_telegram_id(db, payment_in.telegram_id)

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

    client_ip = request.client.host if request.client else "unknown"
    logger.info("robokassa_webhook_received", inv_id=inv_id, client_ip=client_ip)

    if not verify_result_signature(
        password2=settings.robokassa_password2,
        out_sum=out_sum,
        inv_id=inv_id,
        signature_value=signature_value,
    ):
        logger.warning("robokassa_invalid_signature", inv_id=inv_id)
        return "bad sign"

    # Parse payment ID
    try:
        payment_id = int(inv_id)
    except ValueError:
        logger.warning("robokassa_invalid_inv_id", inv_id=inv_id)
        return "bad inv_id"

    # Atomically mark payment as completed ONLY if it's still pending
    update_result = await db.execute(
        update(Payment)
        .where(Payment.id == payment_id, Payment.status == PaymentStatus.PENDING)
        .values(
            status=PaymentStatus.COMPLETED,
            completed_at=datetime.now(UTC),
        )
        .returning(Payment.user_id, Payment.credits)
    )
    row = update_result.fetchone()
    if row is None:
        # Either payment not found or already completed — idempotent
        # Check if payment even exists to return correct response
        existing = await db.get(Payment, payment_id)
        if not existing:
            logger.warning("robokassa_payment_not_found", inv_id=inv_id)
            return "bad inv_id"
        # Already completed — idempotent success
        return f"OK{inv_id}"

    user_id, credits = row.user_id, row.credits

    # Atomically add credits to user
    await db.execute(
        update(User)
        .where(User.id == user_id)
        .values(credits_remaining=User.credits_remaining + credits)
    )

    # Log success (fetch user info for logging)
    user = await db.get(User, user_id)
    if user:
        logger.info(
            "credits_added",
            user_id=user.id,
            telegram_id=user.telegram_id,
            credits_added=credits,
        )

    await db.flush()
    await db.commit()

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
    """Get user's credit balance by Telegram ID.

    REFACT-004: Creates the user if not found, so the returned balance
    always reflects real DB state (1 trial credit for new users).
    """
    user = await get_or_create_user_by_telegram_id(db, telegram_id)
    return BalanceResponse(
        telegram_id=telegram_id,
        credits_remaining=user.credits_remaining,
        total_papers_generated=user.total_papers_generated,
    )


