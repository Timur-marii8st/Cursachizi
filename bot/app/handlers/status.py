"""Job status checking handlers."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message

from bot.app.services.api_client import CourseForgeAPIClient
from shared.schemas.job import JobStage, JobStatus, WorkType

router = Router()

STATUS_ICONS = {
    JobStatus.PENDING: "[pending]",
    JobStatus.RUNNING: "[running]",
    JobStatus.COMPLETED: "[done]",
    JobStatus.FAILED: "[failed]",
    JobStatus.CANCELLED: "[cancelled]",
}

STAGE_NAMES = {
    JobStage.QUEUED: "queued",
    JobStage.RESEARCHING: "researching",
    JobStage.OUTLINING: "outlining",
    JobStage.WRITING: "writing",
    JobStage.FACT_CHECKING: "fact-checking",
    JobStage.FORMATTING: "formatting",
    JobStage.FINALIZING: "finalizing",
}


@router.message(Command("status"))
async def cmd_status(
    message: Message,
    api_client: CourseForgeAPIClient,
) -> None:
    """Check status of the most recent job."""
    try:
        jobs = await api_client.list_jobs(limit=1, offset=0)
        if not jobs:
            await message.answer("No jobs found yet. Start one with /generate")
            return

        job = jobs[0]
        status_icon = STATUS_ICONS.get(job.status, "[?]")

        stage_line = ""
        if job.progress is not None:
            stage_name = STAGE_NAMES.get(job.progress.stage, job.progress.stage)
            stage_line = (
                f"\nStage: {stage_name} ({job.progress.progress_pct}%)"
            )
            if job.progress.message:
                stage_line += f"\nDetail: {job.progress.message}"

        err_line = f"\nОшибка: {job.error_message}" if job.error_message else ""

        await message.answer(
            f"{status_icon} Задание {job.id}\n"
            f"Статус: {job.status}\n"
            f"Тема: {job.topic}"
            f"{stage_line}"
            f"{err_line}"
        )

        # If completed — download and send as Telegram document
        if job.status == JobStatus.COMPLETED and job.document_url:
            try:
                doc_bytes = await api_client.download_document(job.id)
                safe_topic = job.topic[:40].replace("/", "_")
                work_label = (
                    "научная статья" if job.work_type == WorkType.ARTICLE
                    else "курсовая работа"
                )
                filename = f"{work_label.replace(' ', '_')}_{safe_topic}.docx"
                await message.answer_document(
                    BufferedInputFile(doc_bytes, filename=filename),
                    caption=f"Ваша {work_label} готова!",
                )
            except Exception:
                await message.answer(
                    "Документ готов, но не удалось загрузить файл. "
                    "Попробуйте /status ещё раз или обратитесь в поддержку."
                )

    except Exception:
        await message.answer("Не удалось получить статус. Попробуйте позже.")
