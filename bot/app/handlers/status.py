"""Job status checking handlers."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.app.services.api_client import CourseForgeAPIClient
from shared.schemas.job import JobStage, JobStatus

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

        doc_line = f"\nDocument: {job.document_url}" if job.document_url else ""
        err_line = f"\nError: {job.error_message}" if job.error_message else ""

        await message.answer(
            f"{status_icon} Job {job.id}\n"
            f"Status: {job.status}\n"
            f"Topic: {job.topic}"
            f"{stage_line}"
            f"{doc_line}"
            f"{err_line}"
        )
    except Exception:
        await message.answer("Could not fetch status. Please try again later.")
