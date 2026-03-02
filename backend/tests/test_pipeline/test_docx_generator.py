"""Tests for ГОСТ-compliant document generation."""

import io
import pytest
from docx import Document

from backend.app.pipeline.formatter.docx_generator import DocxGenerator
from shared.schemas.pipeline import Outline, OutlineChapter, SectionContent, Source
from shared.schemas.template import GostTemplate, MarginConfig


@pytest.fixture
def generator() -> DocxGenerator:
    return DocxGenerator()


@pytest.fixture
def sample_outline() -> Outline:
    return Outline(
        title="Влияние цифровизации на управление персоналом",
        introduction_points=["Актуальность", "Цель исследования"],
        chapters=[
            OutlineChapter(
                number=1,
                title="Теоретические основы",
                subsections=["1.1 Понятия и определения", "1.2 Обзор литературы"],
                estimated_pages=10,
            ),
            OutlineChapter(
                number=2,
                title="Практический анализ",
                subsections=["2.1 Методология", "2.2 Результаты"],
                estimated_pages=12,
            ),
        ],
        conclusion_points=["Основные выводы"],
    )


@pytest.fixture
def sample_sections() -> list[SectionContent]:
    return [
        SectionContent(
            chapter_number=0,
            section_title="Введение",
            content="Данная курсовая работа посвящена исследованию влияния цифровизации.",
            word_count=10,
        ),
        SectionContent(
            chapter_number=1,
            section_title="1.1 Понятия и определения",
            content="Цифровизация — это процесс внедрения цифровых технологий [1].",
            word_count=10,
            citations=["1"],
        ),
        SectionContent(
            chapter_number=1,
            section_title="1.2 Обзор литературы",
            content="Многие исследователи изучали данную проблему [2].",
            word_count=8,
            citations=["2"],
        ),
        SectionContent(
            chapter_number=2,
            section_title="2.1 Методология",
            content="В исследовании применялись методы анализа и синтеза.",
            word_count=8,
        ),
        SectionContent(
            chapter_number=2,
            section_title="2.2 Результаты",
            content="Результаты исследования показали положительную динамику [3].",
            word_count=8,
            citations=["3"],
        ),
        SectionContent(
            chapter_number=99,
            section_title="Заключение",
            content="В ходе исследования были достигнуты поставленные цели.",
            word_count=8,
        ),
    ]


@pytest.fixture
def sample_bib_sources() -> list[Source]:
    return [
        Source(url="https://example.com/1", title="Иванов И.И. Цифровизация HR"),
        Source(url="https://example.com/2", title="Петров П.П. Управление персоналом"),
        Source(url="https://example.com/3", title="Сидоров С.С. Цифровая экономика"),
    ]


class TestDocxGenerator:
    def test_generates_valid_docx(
        self,
        generator: DocxGenerator,
        sample_outline: Outline,
        sample_sections: list[SectionContent],
        sample_bib_sources: list[Source],
    ) -> None:
        doc_bytes = generator.generate(
            outline=sample_outline,
            sections=sample_sections,
            sources=sample_bib_sources,
            university="Тестовый Университет",
            discipline="Менеджмент",
        )

        assert isinstance(doc_bytes, bytes)
        assert len(doc_bytes) > 0

        # Verify it's a valid docx by opening it
        doc = Document(io.BytesIO(doc_bytes))
        assert len(doc.paragraphs) > 0

    def test_contains_title_page(
        self,
        generator: DocxGenerator,
        sample_outline: Outline,
        sample_sections: list[SectionContent],
        sample_bib_sources: list[Source],
    ) -> None:
        doc_bytes = generator.generate(
            outline=sample_outline,
            sections=sample_sections,
            sources=sample_bib_sources,
            university="МГУ",
        )

        doc = Document(io.BytesIO(doc_bytes))
        text = "\n".join(p.text for p in doc.paragraphs)

        assert "МГУ" in text
        assert "КУРСОВАЯ РАБОТА" in text
        assert sample_outline.title in text

    def test_contains_all_sections(
        self,
        generator: DocxGenerator,
        sample_outline: Outline,
        sample_sections: list[SectionContent],
        sample_bib_sources: list[Source],
    ) -> None:
        doc_bytes = generator.generate(
            outline=sample_outline,
            sections=sample_sections,
            sources=sample_bib_sources,
        )

        doc = Document(io.BytesIO(doc_bytes))
        text = "\n".join(p.text for p in doc.paragraphs)

        assert "ВВЕДЕНИЕ" in text
        assert "ЗАКЛЮЧЕНИЕ" in text
        assert "СПИСОК ИСПОЛЬЗОВАННЫХ ИСТОЧНИКОВ" in text

    def test_bibliography_entries(
        self,
        generator: DocxGenerator,
        sample_outline: Outline,
        sample_sections: list[SectionContent],
        sample_bib_sources: list[Source],
    ) -> None:
        doc_bytes = generator.generate(
            outline=sample_outline,
            sections=sample_sections,
            sources=sample_bib_sources,
        )

        doc = Document(io.BytesIO(doc_bytes))
        text = "\n".join(p.text for p in doc.paragraphs)

        for source in sample_bib_sources:
            assert source.title in text

    def test_page_margins(
        self,
        sample_outline: Outline,
        sample_sections: list[SectionContent],
        sample_bib_sources: list[Source],
    ) -> None:
        """Verify ГОСТ margins: top=20, bottom=20, left=30, right=15."""
        generator = DocxGenerator()
        doc_bytes = generator.generate(
            outline=sample_outline,
            sections=sample_sections,
            sources=sample_bib_sources,
        )

        doc = Document(io.BytesIO(doc_bytes))
        section = doc.sections[0]

        # Margins in EMU (English Metric Units), 1mm = 36000 EMU
        mm_to_emu = 36000
        assert abs(section.top_margin - 20 * mm_to_emu) < mm_to_emu  # ±1mm tolerance
        assert abs(section.bottom_margin - 20 * mm_to_emu) < mm_to_emu
        assert abs(section.left_margin - 30 * mm_to_emu) < mm_to_emu
        assert abs(section.right_margin - 15 * mm_to_emu) < mm_to_emu

    def test_custom_template(
        self,
        sample_outline: Outline,
        sample_sections: list[SectionContent],
        sample_bib_sources: list[Source],
    ) -> None:
        """Test with custom margin configuration."""
        template = GostTemplate(
            margins=MarginConfig(top_mm=25, bottom_mm=25, left_mm=35, right_mm=10),
        )
        generator = DocxGenerator(template=template)

        doc_bytes = generator.generate(
            outline=sample_outline,
            sections=sample_sections,
            sources=sample_bib_sources,
        )

        doc = Document(io.BytesIO(doc_bytes))
        section = doc.sections[0]

        mm_to_emu = 36000
        assert abs(section.left_margin - 35 * mm_to_emu) < mm_to_emu
