"""Tests for source ranking and deduplication."""

import pytest

from backend.app.pipeline.research.ranker import SourceRanker
from shared.schemas.pipeline import Source


@pytest.fixture
def ranker() -> SourceRanker:
    return SourceRanker(min_content_length=50)


class TestSourceRanker:
    def test_keeps_sources_without_content_but_ranks_lower(self, ranker: SourceRanker) -> None:
        """Sources without full_text are preserved (for bibliography) but rank lower."""
        sources = [
            Source(url="https://a.com", title="A", full_text="Short"),
            Source(
                url="https://b.com",
                title="B",
                full_text="This has enough content to pass the filter " * 5,
                relevance_score=0.5,
            ),
        ]

        result = ranker.rank_and_filter(sources)
        # Both sources kept — short content source ranks lower
        assert len(result) == 2
        assert result[0].title == "B"  # longer content + higher relevance ranks higher
        assert result[1].title == "A"  # short content ranks lower

    def test_filters_sources_with_no_title_and_no_url(self, ranker: SourceRanker) -> None:
        """Sources with neither title nor url are truly useless and removed."""
        sources = [
            Source(url="", title="", full_text="Some text"),
            Source(url="https://b.com", title="B", full_text=""),
        ]

        result = ranker.rank_and_filter(sources)
        assert len(result) == 1
        assert result[0].title == "B"

    def test_deduplicates_by_url(self, ranker: SourceRanker) -> None:
        long_text = "x" * 200
        sources = [
            Source(url="https://example.com/page", title="Page 1", full_text=long_text),
            Source(url="https://www.example.com/page/", title="Page 2", full_text=long_text),
            Source(url="http://example.com/page", title="Page 3", full_text=long_text),
        ]

        result = ranker.rank_and_filter(sources)
        assert len(result) == 1

    def test_respects_max_sources(self, ranker: SourceRanker) -> None:
        long_text = "x" * 200
        sources = [
            Source(
                url=f"https://example{i}.com",
                title=f"Source {i}",
                full_text=long_text,
                relevance_score=0.5,
            )
            for i in range(20)
        ]

        result = ranker.rank_and_filter(sources, max_sources=5)
        assert len(result) == 5

    def test_ranks_by_relevance_and_length(self, ranker: SourceRanker) -> None:
        sources = [
            Source(
                url="https://low.com",
                title="Low",
                full_text="x" * 200,
                relevance_score=0.2,
            ),
            Source(
                url="https://high.com",
                title="High",
                full_text="x" * 5000,
                relevance_score=0.9,
            ),
            Source(
                url="https://medium.com",
                title="Medium",
                full_text="x" * 1000,
                relevance_score=0.5,
            ),
        ]

        result = ranker.rank_and_filter(sources)
        assert result[0].title == "High"
        assert result[-1].title == "Low"

    def test_academic_bonus(self, ranker: SourceRanker) -> None:
        long_text = "x" * 200
        sources = [
            Source(
                url="https://regular.com",
                title="Regular",
                full_text=long_text,
                relevance_score=0.5,
                is_academic=False,
            ),
            Source(
                url="https://academic.edu",
                title="Academic",
                full_text=long_text,
                relevance_score=0.5,
                is_academic=True,
            ),
        ]

        result = ranker.rank_and_filter(sources)
        assert result[0].title == "Academic"

    def test_empty_input(self, ranker: SourceRanker) -> None:
        assert ranker.rank_and_filter([]) == []

    def test_url_normalization(self) -> None:
        ranker = SourceRanker()
        assert ranker._normalize_url("https://www.Example.com/Path/") == "example.com/path"
        assert ranker._normalize_url("http://example.com") == "example.com"
        assert ranker._normalize_url("https://sub.example.com/p") == "sub.example.com/p"
