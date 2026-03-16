"""Tests for reference extraction and renumbering."""


from backend.app.pipeline.formatter.reference_extractor import (
    _find_duplicate,
    _normalize_ref,
    _renumber_citations,
    _split_reference_block,
    extract_and_renumber_references,
)
from shared.schemas.pipeline import SectionContent


def _make_section(
    content: str,
    chapter_number: int = 1,
    section_title: str = "Test Section",
) -> SectionContent:
    return SectionContent(
        chapter_number=chapter_number,
        section_title=section_title,
        content=content,
        word_count=len(content.split()),
    )


class TestSplitReferenceBlock:
    def test_no_references(self):
        text = "Some body text without any references."
        refs, body = _split_reference_block(text)
        assert refs == []
        assert body == text

    def test_single_reference(self):
        text = (
            "Body text with citation [1].\n"
            "[1] Russell, S. J. Artificial Intelligence. Pearson, 2021."
        )
        refs, body = _split_reference_block(text)
        assert len(refs) == 1
        assert refs[0][0] == 1
        assert "Russell" in refs[0][1]
        assert body.strip() == "Body text with citation [1]."

    def test_multiple_references(self):
        text = (
            "Body text with citations [1] and [2].\n"
            "[1] Russell, S. J. Artificial Intelligence. Pearson, 2021.\n"
            "[2] Kaplan, A. Siri, Siri... Business Horizons, 2019.\n"
            "[3] Bostrom, N. Superintelligence. Oxford, 2014."
        )
        refs, body = _split_reference_block(text)
        assert len(refs) == 3
        assert refs[0][0] == 1
        assert refs[2][0] == 3
        assert "[1]" in body
        assert "Russell" not in body

    def test_references_with_empty_line_gap(self):
        text = (
            "Body text.\n\n"
            "[1] Russell, S. J. Artificial Intelligence. Pearson, 2021.\n"
            "\n"
            "[2] Kaplan, A. Siri, Siri... Business Horizons, 2019."
        )
        refs, _body = _split_reference_block(text)
        assert len(refs) == 2

    def test_short_lines_not_refs(self):
        """Lines with [N] but too short should not be treated as references."""
        text = (
            "See [1] for details.\n"
            "[1] Short"
        )
        refs, _body = _split_reference_block(text)
        # "Short" is only 5 chars, below the 15-char threshold
        assert len(refs) == 0

    def test_preserves_body_paragraphs(self):
        text = (
            "First paragraph.\n"
            "Second paragraph.\n"
            "Third paragraph.\n\n"
            "[1] Some Long Reference Text That Is Definitely Long Enough."
        )
        refs, body = _split_reference_block(text)
        assert len(refs) == 1
        assert "First paragraph." in body
        assert "Third paragraph." in body


class TestNormalizeRef:
    def test_lowercases(self):
        assert _normalize_ref("Russell, S. J.") == "russell, s. j"

    def test_collapses_spaces(self):
        assert _normalize_ref("  lots   of   space  ") == "lots of space"


class TestFindDuplicate:
    def test_finds_exact_match(self):
        existing = {"russell, s. j. artificial intelligence. pearson, 2021": 1}
        result = _find_duplicate(
            "russell, s. j. artificial intelligence. pearson, 2021", existing
        )
        assert result == 1

    def test_finds_prefix_match(self):
        """Two refs with same first 60 chars should match."""
        existing = {
            "russell, s. j. artificial intelligence: a modern approach. 4th ed. pearson education, 2021": 1
        }
        # Same author/title but different edition detail — first 60 chars match
        result = _find_duplicate(
            "russell, s. j. artificial intelligence: a modern approach. 4th ed. pearson, 2021",
            existing,
        )
        assert result == 1

    def test_no_match(self):
        existing = {"russell, s. j. artificial intelligence": 1}
        result = _find_duplicate("kaplan, a. siri, siri", existing)
        assert result is None


class TestRenumberCitations:
    def test_renumbers(self):
        text = "As shown in [1] and confirmed by [2]."
        mapping = {1: 5, 2: 12}
        result = _renumber_citations(text, mapping)
        assert result == "As shown in [5] and confirmed by [12]."

    def test_unmapped_left_unchanged(self):
        text = "See [1] and [3]."
        mapping = {1: 10}
        result = _renumber_citations(text, mapping)
        assert result == "See [10] and [3]."

    def test_empty_mapping(self):
        text = "No changes [1]."
        result = _renumber_citations(text, {})
        assert result == "No changes [1]."


class TestExtractAndRenumberReferences:
    def test_single_section(self):
        section = _make_section(
            "Some text with [1] citation.\n"
            "[1] Russell, S. J. Artificial Intelligence. Pearson, 2021."
        )
        result = extract_and_renumber_references([section])

        assert len(result.bibliography) == 1
        assert "Russell" in result.bibliography[0]
        assert len(result.sections) == 1
        # Reference block should be removed from body
        assert "Russell" not in result.sections[0].content
        # Inline citation should remain (renumbered to 1)
        assert "[1]" in result.sections[0].content

    def test_two_sections_dedup(self):
        s1 = _make_section(
            "Text with [1] and [2].\n"
            "[1] Russell, S. J. Artificial Intelligence. Pearson, 2021.\n"
            "[2] Kaplan, A. Siri, Siri in my hand. Business Horizons, 2019.",
            section_title="Section 1.1",
        )
        s2 = _make_section(
            "More text [1] and [2].\n"
            "[1] Russell, S. J. Artificial Intelligence. Pearson, 2021.\n"
            "[2] Bostrom, N. Superintelligence: Paths. Oxford, 2014.",
            chapter_number=2,
            section_title="Section 2.1",
        )
        result = extract_and_renumber_references([s1, s2])

        # Russell appears in both but should be deduplicated
        assert len(result.bibliography) == 3  # Russell, Kaplan, Bostrom
        assert "Russell" in result.bibliography[0]

        # In section 2, local [1] (Russell) → global 1, local [2] (Bostrom) → global 3
        s2_text = result.sections[1].content
        assert "[1]" in s2_text  # Russell stays [1]
        assert "[3]" in s2_text  # Bostrom becomes [3]

    def test_no_references_passthrough(self):
        section = _make_section("Plain text without any references at all.")
        result = extract_and_renumber_references([section])

        assert len(result.bibliography) == 0
        assert result.sections[0].content == section.content

    def test_mixed_sections_with_and_without_refs(self):
        s1 = _make_section(
            "Intro text without references.",
            chapter_number=0,
            section_title="Введение",
        )
        s2 = _make_section(
            "Body text [1].\n"
            "[1] Some Author. Some Very Long Book Title Here. Publisher, 2023.",
            section_title="Section 1.1",
        )
        result = extract_and_renumber_references([s1, s2])

        assert len(result.bibliography) == 1
        # Intro unchanged
        assert result.sections[0].content == s1.content

    def test_word_count_updated(self):
        section = _make_section(
            "Short text [1].\n"
            "[1] Author Name. A Very Long Reference Title. Publisher, 2023."
        )
        result = extract_and_renumber_references([section])

        # Word count should reflect the cleaned text, not the original
        cleaned_words = len(result.sections[0].content.split())
        assert result.sections[0].word_count == cleaned_words
