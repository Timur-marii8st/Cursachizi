"""User service — shared user lookup and creation logic."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.user import User


async def get_user_by_telegram_id(db: AsyncSession, telegram_id: int) -> User | None:
    """Look up a user by Telegram ID. Returns None if not found."""
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()


async def get_or_create_user_by_telegram_id(
    db: AsyncSession,
    telegram_id: int,
    *,
    username: str = "",
    first_name: str = "",
    last_name: str = "",
) -> User:
    """Get existing user or create a new one with 1 free trial credit.

    FIX-006: Uses INSERT ... ON CONFLICT DO NOTHING to avoid TOCTOU race condition
    when two concurrent requests try to create the same user simultaneously.
    """
    stmt = pg_insert(User).values(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        credits_remaining=1,
    ).on_conflict_do_nothing(index_elements=["telegram_id"])
    await db.execute(stmt)
    await db.flush()

    # Re-fetch to get the actual row (either newly inserted or pre-existing)
    user = await get_user_by_telegram_id(db, telegram_id)
    assert user is not None, f"User with telegram_id={telegram_id} should exist after upsert"
    return user
