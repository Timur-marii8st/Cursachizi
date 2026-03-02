"""Job status checking handlers."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.app.services.api_client import CourseForgeAPIClient
from shared.schemas.job import JobStatus

router = Router()

STATUS_ICONS = {
    JobStatus.PENDING: "⏳",
    JobStatus.RUNNING: "🔄",
    JobStatus.COMPLETED: "✅",
    JobStatus.FAILED: "❌",
    JobStatus.CANCELLED: "🚫",
}

STAGE_NAMES = {
    "queued": "В очереди",
    "researching": "Исследование темы",
    "outlining": "Составление плана",
    "writing": "Написание текста",
    "fact_checking": "Проверка фактов",
    "formatting": "Форматирование",
    "finalizing": "Завершение",
}


@router.message(Command("status"))
async def cmd_status(
    message: Message,
    api_client: CourseForgeAPIClient,
) -> None:
    """Check status of recent jobs."""
    try:
        # For MVP, we show the most recent job
        # TODO: Filter by telegram user ID
        response = await api_client._base_url  # placeholder
        await message.answer(
            "Функция проверки статуса будет доступна после подключения авторизации.\n"
            "Пока вы можете проверить статус через API: GET /api/jobs"
        )
    except Exception:
        await message.answer(
            "Не удалось получить статус. Попробуйте позже."
        )
