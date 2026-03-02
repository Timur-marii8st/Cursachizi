"""Tests for Pydantic schemas validation."""

import pytest
from pydantic import ValidationError

from shared.schemas.job import JobCreate, JobStatus, JobStage
from shared.schemas.pipeline import PipelineConfig, Source, ClaimVerdict
from shared.schemas.template import GostTemplate, MarginConfig, FontConfig


class TestJobCreate:
    def test_valid_job(self) -> None:
        job = JobCreate(
            topic="Влияние цифровизации на управление персоналом",
            university="МГУ",
            discipline="Менеджмент",
            page_count=30,
        )
        assert job.topic == "Влияние цифровизации на управление персоналом"
        assert job.page_count == 30
        assert job.language == "ru"

    def test_defaults(self) -> None:
        job = JobCreate(topic="Тестовая тема")
        assert job.university == ""
        assert job.discipline == ""
        assert job.page_count == 30
        assert job.template_id is None

    def test_topic_too_short(self) -> None:
        with pytest.raises(ValidationError, match="string_too_short"):
            JobCreate(topic="abc")

    def test_topic_too_long(self) -> None:
        with pytest.raises(ValidationError):
            JobCreate(topic="x" * 501)

    def test_page_count_bounds(self) -> None:
        with pytest.raises(ValidationError):
            JobCreate(topic="Valid topic", page_count=10)  # Below minimum

        with pytest.raises(ValidationError):
            JobCreate(topic="Valid topic", page_count=100)  # Above maximum

    def test_page_count_at_boundaries(self) -> None:
        job_min = JobCreate(topic="Valid topic", page_count=15)
        assert job_min.page_count == 15

        job_max = JobCreate(topic="Valid topic", page_count=80)
        assert job_max.page_count == 80


class TestJobStatus:
    def test_all_statuses(self) -> None:
        assert JobStatus.PENDING == "pending"
        assert JobStatus.RUNNING == "running"
        assert JobStatus.COMPLETED == "completed"
        assert JobStatus.FAILED == "failed"
        assert JobStatus.CANCELLED == "cancelled"


class TestJobStage:
    def test_all_stages(self) -> None:
        stages = [
            JobStage.QUEUED,
            JobStage.RESEARCHING,
            JobStage.OUTLINING,
            JobStage.WRITING,
            JobStage.FACT_CHECKING,
            JobStage.FORMATTING,
            JobStage.FINALIZING,
        ]
        assert len(stages) == 7


class TestPipelineConfig:
    def test_defaults(self) -> None:
        config = PipelineConfig()
        assert config.max_search_results == 20
        assert config.max_sources == 15
        assert config.enable_fact_check is True
        assert config.timeout_seconds == 900

    def test_custom_config(self) -> None:
        config = PipelineConfig(
            max_search_results=50,
            enable_fact_check=False,
            writer_model="gpt-4.1",
        )
        assert config.max_search_results == 50
        assert config.enable_fact_check is False
        assert config.writer_model == "gpt-4.1"

    def test_validation_bounds(self) -> None:
        with pytest.raises(ValidationError):
            PipelineConfig(max_search_results=2)  # Below min

        with pytest.raises(ValidationError):
            PipelineConfig(timeout_seconds=50)  # Below min


class TestSource:
    def test_default_values(self) -> None:
        source = Source(url="https://example.com", title="Test")
        assert source.relevance_score == 0.0
        assert source.is_academic is False
        assert source.language == "ru"
        assert source.full_text == ""

    def test_relevance_bounds(self) -> None:
        with pytest.raises(ValidationError):
            Source(url="https://a.com", title="T", relevance_score=1.5)

        with pytest.raises(ValidationError):
            Source(url="https://a.com", title="T", relevance_score=-0.1)


class TestClaimVerdict:
    def test_values(self) -> None:
        assert ClaimVerdict.SUPPORTED == "supported"
        assert ClaimVerdict.UNSUPPORTED == "unsupported"
        assert ClaimVerdict.UNCERTAIN == "uncertain"


class TestGostTemplate:
    def test_default_is_gost_7_32(self) -> None:
        template = GostTemplate()
        assert template.id == "gost_7_32_2017"
        assert template.margins.left_mm == 30.0
        assert template.margins.right_mm == 15.0
        assert template.margins.top_mm == 20.0
        assert template.margins.bottom_mm == 20.0

    def test_body_defaults(self) -> None:
        template = GostTemplate()
        assert template.body.font.name == "Times New Roman"
        assert template.body.font.size_pt == 14.0
        assert template.body.line_spacing == 1.5
        assert template.body.first_line_indent_mm == 12.5

    def test_heading_styles(self) -> None:
        template = GostTemplate()
        assert template.heading_1.font.bold is True
        assert template.heading_1.uppercase is True
        assert template.heading_1.alignment == "center"
        assert template.heading_2.font.bold is True
        assert template.heading_2.alignment == "left"

    def test_custom_margins(self) -> None:
        margins = MarginConfig(top_mm=25, bottom_mm=25, left_mm=35, right_mm=10)
        template = GostTemplate(margins=margins)
        assert template.margins.left_mm == 35.0

    def test_structural_requirements(self) -> None:
        template = GostTemplate()
        assert template.requires_title_page is True
        assert template.requires_table_of_contents is True
        assert template.requires_introduction is True
        assert template.requires_conclusion is True
        assert template.requires_bibliography is True
        assert template.min_bibliography_entries == 15
