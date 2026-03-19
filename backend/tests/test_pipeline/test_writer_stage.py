"""Tests for section source distribution in the writer stage."""

from __future__ import annotations

from types import SimpleNamespace

from backend.app.pipeline.writer.stage import WriterStage
from backend.app.testing import MockLLMProvider
from shared.schemas.pipeline import (
    BibliographyRegistry,
    Outline,
    OutlineChapter,
    ResearchResult,
    SectionContent,
    Source,
)


def _make_sources(count: int) -> list[Source]:
    return [
        Source(
            url=f"https://example.com/{i}",
            title=f"Source {i}",
            snippet=f"Snippet {i}",
        )
        for i in range(1, count + 1)
    ]


class _FakeSectionWriter:
    def __init__(self) -> None:
        self.required_source_nums: list[list[int]] = []

    async def write_introduction(self, **kwargs) -> SectionContent:
        return SectionContent(
            chapter_number=0,
            section_title="Введение",
            content="Intro",
            word_count=1,
        )

    async def write_section(self, **kwargs) -> SectionContent:
        required_source_nums = kwargs.get("required_source_nums") or []
        self.required_source_nums.append(list(required_source_nums))
        section_title = kwargs["section_title"]
        chapter = kwargs["chapter"]
        return SectionContent(
            chapter_number=chapter.number,
            section_title=section_title,
            content=f"{section_title} body",
            word_count=10,
        )

    async def write_conclusion(self, **kwargs) -> SectionContent:
        return SectionContent(
            chapter_number=99,
            section_title="Заключение",
            content="Conclusion",
            word_count=1,
        )


class TestWriterStageSourceDistribution:
    def test_assign_sources_covers_entire_registry(self) -> None:
        sources = _make_sources(10)
        registry = BibliographyRegistry.from_sources(sources)

        assignments = WriterStage._assign_sources_to_sections(registry, num_sections=4)

        assert len(assignments) == 4
        assert all(assignments)
        assert all(len(section) >= 3 for section in assignments)

        assigned_numbers = {num for section in assignments for num in section}
        expected_numbers = {entry.number for entry in registry.entries}
        assert assigned_numbers == expected_numbers

    async def test_write_all_sections_passes_full_registry_to_sections(self) -> None:
        llm = MockLLMProvider()
        stage = WriterStage(llm)
        fake_writer = _FakeSectionWriter()
        stage._section_writer = fake_writer  # type: ignore[assignment]

        outline = Outline(
            title="Test topic",
            chapters=[
                OutlineChapter(
                    number=1,
                    title="Chapter 1",
                    subsections=["1.1", "1.2"],
                    description="",
                ),
                OutlineChapter(
                    number=2,
                    title="Chapter 2",
                    subsections=["2.1"],
                    description="",
                ),
            ],
        )
        sources = _make_sources(8)
        research = ResearchResult(original_topic="Test topic", sources=sources)
        registry = BibliographyRegistry.from_sources(sources)

        result = await stage.write_all_sections(
            topic="Test topic",
            discipline="Management",
            page_count=24,
            outline=outline,
            research=research,
            config=SimpleNamespace(writer_model="mock-model"),
            bibliography=registry,
        )

        assert len(result) == 5
        assert len(fake_writer.required_source_nums) == 3

        covered_numbers = {
            num
            for section_nums in fake_writer.required_source_nums
            for num in section_nums
        }
        expected_numbers = {entry.number for entry in registry.entries}
        assert covered_numbers == expected_numbers
