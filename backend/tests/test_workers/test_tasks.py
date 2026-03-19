"""Tests for arq worker tasks."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from shared.schemas.job import JobStatus


def _make_mock_job(**overrides) -> MagicMock:
    job = MagicMock()
    job.id = str(uuid4())
    job.status = JobStatus.RUNNING
    job.topic = "Test topic"
    job.discipline = ""
    job.university = ""
    job.page_count = 30
    job.additional_instructions = ""
    job.work_type = "coursework"
    job.reference_s3_key = None
    for k, v in overrides.items():
        setattr(job, k, v)
    return job


def _mock_client() -> MagicMock:
    client = MagicMock()
    client.aclose = AsyncMock()
    return client


class TestRunPipelineCancellationCheck:
    """BUG-002: worker must not overwrite CANCELLED status with COMPLETED."""

    async def test_cancelled_job_not_marked_completed(self) -> None:
        """If job.status == CANCELLED when pipeline finishes, keep CANCELLED."""
        job_id = str(uuid4())

        # Job starts as RUNNING, then gets CANCELLED during pipeline execution
        running_job = _make_mock_job(id=job_id, status=JobStatus.RUNNING)
        cancelled_job = _make_mock_job(id=job_id, status=JobStatus.CANCELLED)

        mock_result = MagicMock()
        mock_result.document_bytes = None
        mock_result.research = None
        mock_result.outline = None
        mock_result.fact_check = None

        # Session call 1: startup (mark RUNNING) → returns running_job
        # Session call 2: completion check → returns cancelled_job (simulates cancel during pipeline)
        startup_session = AsyncMock()
        startup_session.get = AsyncMock(return_value=running_job)
        startup_session.commit = AsyncMock()

        completion_session = AsyncMock()
        completion_session.get = AsyncMock(return_value=cancelled_job)
        completion_session.commit = AsyncMock()

        session_context_managers = [startup_session, completion_session]

        class _SessionContext:
            def __init__(self, session):
                self._session = session

            async def __aenter__(self):
                return self._session

            async def __aexit__(self, *args):
                pass

        call_count = 0

        def _session_factory():
            nonlocal call_count
            session = session_context_managers[min(call_count, len(session_context_managers) - 1)]
            call_count += 1
            return _SessionContext(session)

        with (
            patch("backend.app.workers.tasks.AsyncSessionLocal", side_effect=_session_factory),
            patch("backend.app.workers.tasks.get_settings") as mock_settings,
            patch("backend.app.workers.tasks.get_llm_provider", return_value=_mock_client()),
            patch("backend.app.workers.tasks.get_search_provider", return_value=_mock_client()),
            patch("backend.app.workers.tasks.get_vision_llm_provider", return_value=None),
            patch("backend.app.workers.tasks.PipelineOrchestrator") as mock_orch_cls,
        ):
            settings = MagicMock()
            settings.google_translate_api_key = ""
            settings.deepl_api_key = ""
            settings.visual_match_enabled = False
            settings.max_search_results = 5
            settings.max_sources_per_topic = 10
            settings.max_tokens_per_section = 2000
            settings.default_writer_model = "gemini"
            settings.default_light_model = "gemini"
            settings.pipeline_timeout_seconds = 120
            mock_settings.return_value = settings

            mock_orch = AsyncMock()
            mock_orch.run = AsyncMock(return_value=mock_result)
            mock_orch_cls.return_value = mock_orch

            from backend.app.workers.tasks import run_pipeline
            result = await run_pipeline({}, job_id)

        # The return message must indicate cancellation, not completion
        assert "cancelled" in result.lower()
        # The CANCELLED job's status must NOT have been changed to COMPLETED
        assert cancelled_job.status == JobStatus.CANCELLED
        completion_session.commit.assert_not_called()

    async def test_completed_job_marked_completed_normally(self) -> None:
        """Normal completion: job status RUNNING → COMPLETED."""
        job_id = str(uuid4())

        running_job = _make_mock_job(id=job_id, status=JobStatus.RUNNING)
        still_running_job = _make_mock_job(id=job_id, status=JobStatus.RUNNING)

        mock_result = MagicMock()
        mock_result.document_bytes = None
        mock_result.research = None
        mock_result.outline = None
        mock_result.fact_check = None

        startup_session = AsyncMock()
        startup_session.get = AsyncMock(return_value=running_job)
        startup_session.commit = AsyncMock()
        startup_session.flush = AsyncMock()

        completion_session = AsyncMock()
        completion_session.get = AsyncMock(return_value=still_running_job)
        completion_session.commit = AsyncMock()
        completion_session.flush = AsyncMock()

        class _SessionContext:
            def __init__(self, session):
                self._session = session

            async def __aenter__(self):
                return self._session

            async def __aexit__(self, *args):
                pass

        sessions = [startup_session, completion_session]
        call_count = 0

        def _session_factory():
            nonlocal call_count
            session = sessions[min(call_count, len(sessions) - 1)]
            call_count += 1
            return _SessionContext(session)

        with (
            patch("backend.app.workers.tasks.AsyncSessionLocal", side_effect=_session_factory),
            patch("backend.app.workers.tasks.get_settings") as mock_settings,
            patch("backend.app.workers.tasks.get_llm_provider", return_value=_mock_client()),
            patch("backend.app.workers.tasks.get_search_provider", return_value=_mock_client()),
            patch("backend.app.workers.tasks.get_vision_llm_provider", return_value=None),
            patch("backend.app.workers.tasks.PipelineOrchestrator") as mock_orch_cls,
        ):
            settings = MagicMock()
            settings.google_translate_api_key = ""
            settings.deepl_api_key = ""
            settings.visual_match_enabled = False
            settings.max_search_results = 5
            settings.max_sources_per_topic = 10
            settings.max_tokens_per_section = 2000
            settings.default_writer_model = "gemini"
            settings.default_light_model = "gemini"
            settings.pipeline_timeout_seconds = 120
            mock_settings.return_value = settings

            mock_orch = AsyncMock()
            mock_orch.run = AsyncMock(return_value=mock_result)
            mock_orch_cls.return_value = mock_orch

            from backend.app.workers.tasks import run_pipeline
            result = await run_pipeline({}, job_id)

        assert "completed" in result.lower()
        assert still_running_job.status == JobStatus.COMPLETED
        completion_session.commit.assert_called_once()

    async def test_timeout_sets_informative_error_message(self) -> None:
        """Timeouts must persist a descriptive error instead of an empty string."""
        job_id = str(uuid4())

        startup_job = _make_mock_job(id=job_id, status=JobStatus.RUNNING)
        failed_job = _make_mock_job(id=job_id, status=JobStatus.RUNNING)
        failed_job.stage = "fact_checking"
        failed_job.stage_message = "Проверено 14/25 утверждений"

        startup_session = AsyncMock()
        startup_session.get = AsyncMock(return_value=startup_job)
        startup_session.commit = AsyncMock()

        failure_session = AsyncMock()
        failure_session.get = AsyncMock(return_value=failed_job)
        failure_session.commit = AsyncMock()

        class _SessionContext:
            def __init__(self, session):
                self._session = session

            async def __aenter__(self):
                return self._session

            async def __aexit__(self, *args):
                pass

        sessions = [startup_session, failure_session]
        call_count = 0

        def _session_factory():
            nonlocal call_count
            session = sessions[min(call_count, len(sessions) - 1)]
            call_count += 1
            return _SessionContext(session)

        async def _raise_timeout(awaitable, timeout):
            awaitable.close()
            raise TimeoutError()

        with (
            patch("backend.app.workers.tasks.AsyncSessionLocal", side_effect=_session_factory),
            patch("backend.app.workers.tasks.get_settings") as mock_settings,
            patch("backend.app.workers.tasks.get_llm_provider", return_value=_mock_client()),
            patch("backend.app.workers.tasks.get_search_provider", return_value=_mock_client()),
            patch("backend.app.workers.tasks.get_vision_llm_provider", return_value=None),
            patch("backend.app.workers.tasks.PipelineOrchestrator") as mock_orch_cls,
            patch(
                "backend.app.workers.tasks.asyncio.wait_for",
                new=AsyncMock(side_effect=_raise_timeout),
            ),
        ):
            settings = MagicMock()
            settings.google_translate_api_key = ""
            settings.deepl_api_key = ""
            settings.visual_match_enabled = False
            settings.max_search_results = 5
            settings.max_sources_per_topic = 10
            settings.max_tokens_per_section = 2000
            settings.default_writer_model = "gemini"
            settings.default_light_model = "gemini"
            settings.pipeline_timeout_seconds = 120
            mock_settings.return_value = settings

            mock_orch = AsyncMock()
            mock_orch.run = AsyncMock()
            mock_orch_cls.return_value = mock_orch

            from backend.app.workers.tasks import run_pipeline
            result = await run_pipeline({}, job_id)

        assert "timed out after 120 seconds" in result
        assert "fact_checking" in result
        assert "14/25" in result
        assert failed_job.status == JobStatus.FAILED
        assert failed_job.error_message == (
            "Pipeline timed out after 120 seconds during stage 'fact_checking' "
            "(Проверено 14/25 утверждений)"
        )
        failure_session.commit.assert_called_once()


class TestRunPipelineErrorFormatting:
    """Worker must persist meaningful errors for empty exceptions and timeouts."""

    async def test_timeout_error_gets_meaningful_message(self) -> None:
        job_id = str(uuid4())

        running_job = _make_mock_job(id=job_id, status=JobStatus.RUNNING)
        failed_job = _make_mock_job(id=job_id, status=JobStatus.RUNNING)

        startup_session = AsyncMock()
        startup_session.get = AsyncMock(return_value=running_job)
        startup_session.commit = AsyncMock()

        failure_session = AsyncMock()
        failure_session.get = AsyncMock(return_value=failed_job)
        failure_session.commit = AsyncMock()

        class _SessionContext:
            def __init__(self, session):
                self._session = session

            async def __aenter__(self):
                return self._session

            async def __aexit__(self, *args):
                pass

        sessions = [startup_session, failure_session]
        call_count = 0

        def _session_factory():
            nonlocal call_count
            session = sessions[min(call_count, len(sessions) - 1)]
            call_count += 1
            return _SessionContext(session)

        with (
            patch("backend.app.workers.tasks.AsyncSessionLocal", side_effect=_session_factory),
            patch("backend.app.workers.tasks.get_settings") as mock_settings,
            patch("backend.app.workers.tasks.get_llm_provider", return_value=_mock_client()),
            patch("backend.app.workers.tasks.get_search_provider", return_value=_mock_client()),
            patch("backend.app.workers.tasks.get_vision_llm_provider", return_value=None),
            patch("backend.app.workers.tasks.PipelineOrchestrator") as mock_orch_cls,
        ):
            settings = MagicMock()
            settings.google_translate_api_key = ""
            settings.deepl_api_key = ""
            settings.visual_match_enabled = False
            settings.max_search_results = 5
            settings.max_sources_per_topic = 10
            settings.max_tokens_per_section = 2000
            settings.default_writer_model = "gemini"
            settings.default_light_model = "gemini"
            settings.pipeline_timeout_seconds = 120
            mock_settings.return_value = settings

            mock_orch = AsyncMock()
            mock_orch.run = AsyncMock(side_effect=TimeoutError())
            mock_orch_cls.return_value = mock_orch

            from backend.app.workers.tasks import run_pipeline
            result = await run_pipeline({}, job_id)

        assert "timed out" in result.lower()
        assert "timed out" in failed_job.error_message.lower()
        assert failed_job.error_message
        assert failed_job.status == JobStatus.FAILED
        failure_session.commit.assert_called_once()

    async def test_empty_exception_uses_class_name(self) -> None:
        job_id = str(uuid4())

        running_job = _make_mock_job(id=job_id, status=JobStatus.RUNNING)
        failed_job = _make_mock_job(id=job_id, status=JobStatus.RUNNING)

        startup_session = AsyncMock()
        startup_session.get = AsyncMock(return_value=running_job)
        startup_session.commit = AsyncMock()

        failure_session = AsyncMock()
        failure_session.get = AsyncMock(return_value=failed_job)
        failure_session.commit = AsyncMock()

        class _SessionContext:
            def __init__(self, session):
                self._session = session

            async def __aenter__(self):
                return self._session

            async def __aexit__(self, *args):
                pass

        sessions = [startup_session, failure_session]
        call_count = 0

        def _session_factory():
            nonlocal call_count
            session = sessions[min(call_count, len(sessions) - 1)]
            call_count += 1
            return _SessionContext(session)

        with (
            patch("backend.app.workers.tasks.AsyncSessionLocal", side_effect=_session_factory),
            patch("backend.app.workers.tasks.get_settings") as mock_settings,
            patch("backend.app.workers.tasks.get_llm_provider", return_value=_mock_client()),
            patch("backend.app.workers.tasks.get_search_provider", return_value=_mock_client()),
            patch("backend.app.workers.tasks.get_vision_llm_provider", return_value=None),
            patch("backend.app.workers.tasks.PipelineOrchestrator") as mock_orch_cls,
        ):
            settings = MagicMock()
            settings.google_translate_api_key = ""
            settings.deepl_api_key = ""
            settings.visual_match_enabled = False
            settings.max_search_results = 5
            settings.max_sources_per_topic = 10
            settings.max_tokens_per_section = 2000
            settings.default_writer_model = "gemini"
            settings.default_light_model = "gemini"
            settings.pipeline_timeout_seconds = 120
            mock_settings.return_value = settings

            mock_orch = AsyncMock()
            mock_orch.run = AsyncMock(side_effect=Exception())
            mock_orch_cls.return_value = mock_orch

            from backend.app.workers.tasks import run_pipeline
            result = await run_pipeline({}, job_id)

        assert "exception" in result.lower()
        assert failed_job.error_message == "Exception"
        assert failed_job.status == JobStatus.FAILED
        failure_session.commit.assert_called_once()
