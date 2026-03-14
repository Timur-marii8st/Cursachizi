"""Tests for citation_fixer — remapping LLM citations to real registry entries."""


from backend.app.pipeline.writer.citation_fixer import (
    _build_citation_mapping,
    _extract_bibliography_block,
    _extract_keywords,
    _remap_citations,
    _strip_bibliography_headers,
    _strip_section_heading,
    fix_citations,
)
from shared.schemas.pipeline import BibliographyRegistry, SectionContent, Source


def _make_registry(n: int = 5) -> BibliographyRegistry:
    """Create a test registry with N entries."""
    sources = [
        Source(
            url=f"https://example.com/{i}",
            title=f"Источник {i}: Тема номер {i}",
            snippet=f"Описание источника {i}",
        )
        for i in range(1, n + 1)
    ]
    return BibliographyRegistry.from_sources(sources)


class TestExtractBibliographyBlock:
    """Test _extract_bibliography_block."""

    def test_extracts_standard_block(self):
        text = (
            "Body text with [1] citation.\n\n"
            "[1] Иванов И.И. Название книги. — М., 2020.\n"
            "[2] Петров П.П. Другая книга. — СПб., 2021."
        )
        refs, body = _extract_bibliography_block(text)
        assert 1 in refs
        assert 2 in refs
        assert "Иванов" in refs[1]
        assert "Body text" in body
        assert "Иванов" not in body

    def test_no_block(self):
        text = "Just body text with [1] inline."
        refs, body = _extract_bibliography_block(text)
        assert refs == {}
        assert body == text

    def test_block_with_header(self):
        text = (
            "Body text.\n\n"
            "Библиографические ссылки:\n"
            "[1] Автор. Название. — М., 2020."
        )
        refs, body = _extract_bibliography_block(text)
        assert 1 in refs
        assert "Body text" in body

    def test_empty_text(self):
        refs, body = _extract_bibliography_block("")
        assert refs == {}
        assert body == ""


class TestStripBibliographyHeaders:
    """Test _strip_bibliography_headers."""

    def test_strips_russian_header(self):
        text = "Body text.\n\nБиблиографические ссылки:\n"
        result = _strip_bibliography_headers(text)
        assert "Библиографические" not in result
        assert "Body text" in result

    def test_strips_list_header(self):
        text = "Body.\n\nСписок литературы:"
        result = _strip_bibliography_headers(text)
        assert "Список литературы" not in result

    def test_strips_sources_header(self):
        text = "Body.\nИсточники:"
        result = _strip_bibliography_headers(text)
        assert "Источники" not in result

    def test_preserves_normal_text(self):
        text = "Body text without headers."
        result = _strip_bibliography_headers(text)
        assert result == text


class TestStripSectionHeading:
    """Test _strip_section_heading."""

    def test_strips_exact_match(self):
        text = "1.1 Понятийный аппарат\nТекст раздела."
        result = _strip_section_heading(text, "1.1 Понятийный аппарат")
        assert result == "Текст раздела."

    def test_strips_numbered_heading(self):
        text = "1.2 Другой заголовок\nТекст."
        result = _strip_section_heading(text, "1.2 Другой заголовок")
        assert result == "Текст."

    def test_strips_razdel_prefix(self):
        text = "РАЗДЕЛ: 2.2 ИИ как объект\nТекст раздела."
        result = _strip_section_heading(text, "2.2 ИИ как объект")
        assert "РАЗДЕЛ" not in result
        assert "Текст раздела" in result

    def test_strips_introduction(self):
        text = "ВВЕДЕНИЕ\nТекст введения."
        result = _strip_section_heading(text, "Введение")
        assert result == "Текст введения."

    def test_preserves_no_heading(self):
        text = "Текст без заголовка в начале."
        result = _strip_section_heading(text, "1.1 Title")
        assert result == text

    def test_case_insensitive(self):
        text = "введение\nТекст."
        result = _strip_section_heading(text, "Введение")
        assert result == "Текст."


class TestBuildCitationMapping:
    """Test _build_citation_mapping with fuzzy matching."""

    def test_maps_similar_titles(self):
        fake_refs = {
            1: "Источник 1 о теме номер 1. — М., 2020.",
            2: "Источник 3 по теме номер 3. — СПб., 2021.",
        }
        registry = _make_registry(5)
        mapping = _build_citation_mapping(fake_refs, registry)

        # Should map fake ref 1 → registry entry 1 (similar keywords)
        assert 1 in mapping
        # Should map fake ref 2 → registry entry 3 (similar keywords)
        assert 2 in mapping

    def test_empty_refs(self):
        registry = _make_registry(3)
        mapping = _build_citation_mapping({}, registry)
        assert mapping == {}

    def test_no_match(self):
        fake_refs = {1: "Completely Unrelated English Text About Nothing"}
        registry = _make_registry(3)
        mapping = _build_citation_mapping(fake_refs, registry)
        # May or may not find a match depending on keyword overlap
        # At minimum, should not crash
        assert isinstance(mapping, dict)


class TestRemapCitations:
    """Test _remap_citations."""

    def test_remaps_with_mapping(self):
        text = "According to [1] and [2], this is true."
        mapping = {1: 5, 2: 3}
        result, remapped, invalid = _remap_citations(text, mapping, 10)
        assert "[5]" in result
        assert "[3]" in result
        assert "[1]" not in result
        assert "[2]" not in result
        assert remapped == 2

    def test_keeps_valid_numbers(self):
        text = "Source [3] says this."
        mapping = {}
        result, remapped, invalid = _remap_citations(text, mapping, 5)
        assert "[3]" in result
        assert remapped == 0

    def test_remaps_out_of_range(self):
        text = "Source [15] and [20]."
        mapping = {}
        result, remapped, invalid = _remap_citations(text, mapping, 5)
        # Should remap to valid range
        import re
        cited = set(int(m) for m in re.findall(r"\[(\d+)\]", result))
        assert all(1 <= n <= 5 for n in cited)

    def test_no_citations(self):
        text = "No citations here."
        result, remapped, invalid = _remap_citations(text, {}, 5)
        assert result == text
        assert remapped == 0


class TestExtractKeywords:
    """Test _extract_keywords."""

    def test_extracts_russian_words(self):
        keywords = _extract_keywords("Искусственный интеллект в праве")
        assert "искусственный" in keywords
        assert "интеллект" in keywords
        assert "праве" in keywords

    def test_filters_short_words(self):
        keywords = _extract_keywords("ИИ в РФ и ЕС")
        # All words are < 3 chars
        assert len(keywords) == 0

    def test_filters_stopwords(self):
        keywords = _extract_keywords("для этого все было сделано")
        assert "для" not in keywords
        assert "все" not in keywords


class TestFixCitationsIntegration:
    """Integration tests for fix_citations."""

    def test_complete_flow(self):
        """Test the full citation fixing pipeline."""
        sources = [
            Source(url="https://cyberleninka.ru/ai", title="ИИ и право: анализ проблем"),
            Source(url="https://example.com/regulation", title="Регулирование технологий"),
            Source(url="https://example.com/ethics", title="Этика искусственного интеллекта"),
        ]
        registry = BibliographyRegistry.from_sources(sources)

        sections = [
            SectionContent(
                chapter_number=0,
                section_title="Введение",
                content="ВВЕДЕНИЕ\nТекст введения о проблемах ИИ.",
                word_count=6,
            ),
            SectionContent(
                chapter_number=1,
                section_title="1.1 Основные понятия",
                content=(
                    "1.1 Основные понятия\n"
                    "Согласно исследованию [1], технологии ИИ развиваются [2].\n\n"
                    "[1] Автор А. Книга о технологиях. — М., 2020.\n"
                    "[2] Автор Б. Регулирование. — СПб., 2021."
                ),
                word_count=10,
            ),
            SectionContent(
                chapter_number=99,
                section_title="Заключение",
                content="Заключение: исследование завершено.\n\nБиблиографические ссылки:",
                word_count=4,
            ),
        ]

        result = fix_citations(sections, registry)

        # Section headings should be stripped
        assert not result[0].content.upper().startswith("ВВЕДЕНИЕ")
        assert not result[1].content.startswith("1.1 Основные понятия")

        # Bibliography blocks should be stripped
        for section in result:
            assert "Библиографические ссылки" not in section.content
            assert "Автор А. Книга" not in section.content

        # Citations should be in valid range
        import re
        for section in result:
            cited = [int(m) for m in re.findall(r"\[(\d+)\]", section.content)]
            for n in cited:
                assert 1 <= n <= 3, f"Citation [{n}] out of range in {section.section_title}"

    def test_handles_23_citations_11_sources(self):
        """Simulate the real-world bug: 23 citations but only 11 sources."""
        sources = [
            Source(url=f"https://example.com/{i}", title=f"Source {i}")
            for i in range(1, 12)  # 11 sources
        ]
        registry = BibliographyRegistry.from_sources(sources)

        # Create text with citations [1]-[23]
        text_parts = []
        for i in range(1, 24):
            text_parts.append(f"Claim number {i} is supported [{i}].")
        content = " ".join(text_parts)

        sections = [
            SectionContent(
                chapter_number=1,
                section_title="Test",
                content=content,
                word_count=100,
            ),
        ]

        result = fix_citations(sections, registry)

        import re
        cited = set(int(m) for m in re.findall(r"\[(\d+)\]", result[0].content))
        # ALL citations should be in valid range [1]-[11]
        for n in cited:
            assert 1 <= n <= 11, f"Citation [{n}] still out of range!"

    def test_empty_registry_returns_unchanged(self):
        registry = BibliographyRegistry(entries=[])
        sections = [
            SectionContent(
                chapter_number=1,
                section_title="Test",
                content="Text [1] [2].",
                word_count=3,
            ),
        ]
        result = fix_citations(sections, registry)
        assert result[0].content == "Text [1] [2]."
