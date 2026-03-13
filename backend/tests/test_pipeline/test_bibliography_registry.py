"""Tests for BibliographyRegistry — unified bibliography from real sources."""


from shared.schemas.pipeline import BibliographyRegistry, Source


def _make_sources(n: int = 5) -> list[Source]:
    """Create N test Source objects."""
    return [
        Source(
            url=f"https://example.com/source-{i}",
            title=f"Test Source Title {i}",
            snippet=f"Snippet for source {i}",
            full_text=f"Full text content for source {i} " * 20,
            relevance_score=0.9 - i * 0.1,
        )
        for i in range(1, n + 1)
    ]


class TestBibliographyRegistryFromSources:
    """Test BibliographyRegistry.from_sources()."""

    def test_creates_entries_from_sources(self):
        sources = _make_sources(3)
        registry = BibliographyRegistry.from_sources(sources)

        assert len(registry.entries) == 3
        assert registry.entries[0].number == 1
        assert registry.entries[1].number == 2
        assert registry.entries[2].number == 3

    def test_entries_have_correct_titles(self):
        sources = _make_sources(2)
        registry = BibliographyRegistry.from_sources(sources)

        assert registry.entries[0].title == "Test Source Title 1"
        assert registry.entries[1].title == "Test Source Title 2"

    def test_entries_have_formatted_references(self):
        sources = _make_sources(1)
        registry = BibliographyRegistry.from_sources(sources)

        ref = registry.entries[0].formatted_reference
        assert "Test Source Title 1" in ref
        assert "[Электронный ресурс]" in ref
        assert "https://example.com/source-1" in ref

    def test_source_without_url(self):
        source = Source(url="", title="Book Title", snippet="A book")
        registry = BibliographyRegistry.from_sources([source])

        assert registry.entries[0].formatted_reference == "Book Title"
        assert "[Электронный ресурс]" not in registry.entries[0].formatted_reference

    def test_empty_sources(self):
        registry = BibliographyRegistry.from_sources([])
        assert len(registry.entries) == 0


class TestBibliographyRegistryFormatForPrompt:
    """Test format_for_prompt() output."""

    def test_formats_all_entries(self):
        sources = _make_sources(3)
        registry = BibliographyRegistry.from_sources(sources)

        text = registry.format_for_prompt()
        assert "[1]" in text
        assert "[2]" in text
        assert "[3]" in text
        assert "Test Source Title 1" in text

    def test_respects_max_entries(self):
        sources = _make_sources(5)
        registry = BibliographyRegistry.from_sources(sources)

        text = registry.format_for_prompt(max_entries=2)
        assert "[1]" in text
        assert "[2]" in text
        assert "[3]" not in text

    def test_empty_registry(self):
        registry = BibliographyRegistry(entries=[])
        text = registry.format_for_prompt()
        assert "не найдены" in text.lower()


class TestBibliographyRegistryFormatWithContent:
    """Test format_with_content() output."""

    def test_includes_content_for_first_n_sources(self):
        sources = _make_sources(3)
        registry = BibliographyRegistry.from_sources(sources)

        text = registry.format_with_content(sources, max_content_entries=2)
        # First 2 should have full text
        assert "Full text content for source 1" in text
        assert "Full text content for source 2" in text
        # Third should only have title (no full text)
        lines = text.split("\n")
        # Find the line with [3] — it should just be the title
        line3 = [l for l in lines if l.startswith("[3]")]
        assert len(line3) == 1
        assert "Full text content" not in line3[0]

    def test_empty_sources(self):
        registry = BibliographyRegistry(entries=[])
        text = registry.format_with_content([])
        assert "не предоставлены" in text.lower()


class TestBibliographyRegistryGetEntry:
    """Test get_entry() lookup."""

    def test_finds_existing_entry(self):
        sources = _make_sources(3)
        registry = BibliographyRegistry.from_sources(sources)

        entry = registry.get_entry(2)
        assert entry is not None
        assert entry.number == 2
        assert entry.title == "Test Source Title 2"

    def test_returns_none_for_missing(self):
        sources = _make_sources(3)
        registry = BibliographyRegistry.from_sources(sources)

        assert registry.get_entry(99) is None


class TestBibliographyRegistryValidateCitations:
    """Test validate_citations() — finding invalid [N] refs in text."""

    def test_all_valid(self):
        sources = _make_sources(5)
        registry = BibliographyRegistry.from_sources(sources)

        text = "According to [1], and also [3] and [5]."
        invalid = registry.validate_citations(text)
        assert invalid == []

    def test_finds_invalid_citations(self):
        sources = _make_sources(3)
        registry = BibliographyRegistry.from_sources(sources)

        text = "Source [1] says X, but [7] and [15] don't exist."
        invalid = registry.validate_citations(text)
        assert invalid == [7, 15]

    def test_no_citations(self):
        sources = _make_sources(3)
        registry = BibliographyRegistry.from_sources(sources)

        text = "No citations in this text."
        invalid = registry.validate_citations(text)
        assert invalid == []
