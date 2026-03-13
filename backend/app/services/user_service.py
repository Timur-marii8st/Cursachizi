"""User service — shared user lookup and creation logic."""

from sqlalchemy import select
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
    """Get existing user or create a new one with 1 free trial credit."""
    user = await get_user_by_telegram_id(db, telegram_id)
    if user:
        return user
    user = User(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        credits_remaining=1,
    )
    db.add(user)
    await db.flush()
    return user
