"""Tests for source diversity checker."""

import pytest

from backend.app.pipeline.research.diversity_checker import (
    SourceDiversityChecker,
)
from backend.app.testing import MockSearchProvider
from shared.schemas.pipeline import Source


def _make_source(url: str, title: str = "Test", is_academic: bool = False) -> Source:
    return Source(
        url=url,
        title=title,
        snippet="Test snippet",
        full_text="Full text " * 50,
        relevance_score=0.8,
        is_academic=is_academic,
    )


@pytest.fixture
def diverse_sources() -> list[Source]:
    """Sources from 6 different domains, including 3 academic."""
    return [
        _make_source("https://cyberleninka.ru/article/1", "Статья 1"),
        _make_source("https://elibrary.ru/article/2", "Статья 2"),
        _make_source("https://scholar.google.com/3", "Статья 3"),
        _make_source("https://example.com/4", "Сайт 1"),
        _make_source("https://habr.com/5", "Хабр"),
        _make_source("https://rbc.ru/6", "РБК"),
        _make_source("https://tass.ru/7", "ТАСС"),
        _make_source("https://kommersant.ru/8", "Коммерсант"),
        _make_source("https://forbes.ru/9", "Forbes"),
        _make_source("https://vedomosti.ru/10", "Ведомости"),
        _make_source("https://ria.ru/11", "РИА"),
        _make_source("https://lenta.ru/12", "Лента"),
        _make_source("https://iz.ru/13", "Известия"),
        _make_source("https://gazeta.ru/14", "Газета"),
        _make_source("https://expert.ru/15", "Эксперт"),
    ]


@pytest.fixture
def poor_sources() -> list[Source]:
    """Sources mostly from Wikipedia, few unique domains."""
    return [
        _make_source("https://ru.wikipedia.org/1", "Wiki 1"),
        _make_source("https://ru.wikipedia.org/2", "Wiki 2"),
        _make_source("https://ru.wikipedia.org/3", "Wiki 3"),
        _make_source("https://example.com/4", "Сайт"),
    ]


class TestSourceDiversityChecker:
    def test_sufficient_diversity(
        self, mock_search: MockSearchProvider, diverse_sources: list[Source]
    ) -> None:
        checker = SourceDiversityChecker(search=mock_search)
        report = checker.analyze(diverse_sources)

        assert report.is_sufficient
        assert report.total_sources >= 15
        assert report.unique_domains >= 5
        assert report.academic_count >= 3

    def test_insufficient_sources(
        self, mock_search: MockSearchProvider, poor_sources: list[Source]
    ) -> None:
        checker = SourceDiversityChecker(search=mock_search)
        report = checker.analyze(poor_sources)

        assert not report.is_sufficient
        assert report.needs_more_sources
        assert report.needs_more_academic
        assert report.wikipedia_count == 3

    def test_low_diversity(self, mock_search: MockSearchProvider) -> None:
        # 15 sources but all from same domain
        sources = [
            _make_source(f"https://example.com/page{i}", f"Page {i}")
            for i in range(15)
        ]
        checker = SourceDiversityChecker(search=mock_search)
        report = checker.analyze(sources)

        assert not report.is_sufficient
        assert report.unique_domains == 1
        assert report.needs_more_diversity

    def test_academic_detection(self, mock_search: MockSearchProvider) -> None:
        sources = [
            _make_source("https://cyberleninka.ru/article/test"),
            _make_source("https://elibrary.ru/item.asp?id=123"),
            _make_source("https://scholar.google.com/citations"),
            _make_source("https://arxiv.org/abs/2024.12345"),
            _make_source("https://random-blog.ru/post"),
        ]
        checker = SourceDiversityChecker(search=mock_search)
        report = checker.analyze(sources)

        assert report.academic_count == 4
        # Verify is_academic was set on the source objects
        assert sources[0].is_academic is True
        assert sources[4].is_academic is False

    async def test_improve_adds_academic_sources(
        self, mock_search: MockSearchProvider, poor_sources: list[Source]
    ) -> None:
        # Mock search to return academic results
        mock_search.set_results([
            _make_source("https://cyberleninka.ru/new1", "Новая статья 1"),
            _make_source("https://elibrary.ru/new2", "Новая статья 2"),
        ])
        checker = SourceDiversityChecker(search=mock_search)
        report = checker.analyze(poor_sources)

        improved = await checker.improve(
            sources=poor_sources, topic="Цифровизация", report=report
        )

        assert len(improved) > len(poor_sources)
        assert any("cyberleninka" in s.url for s in improved)

    async def test_improve_skips_when_sufficient(
        self, mock_search: MockSearchProvider, diverse_sources: list[Source]
    ) -> None:
        checker = SourceDiversityChecker(search=mock_search)
        report = checker.analyze(diverse_sources)

        improved = await checker.improve(
            sources=diverse_sources, topic="Тема", report=report
        )

        assert improved == diverse_sources
        assert len(mock_search.queries) == 0  # No additional searches

    async def test_improve_deduplicates(
        self, mock_search: MockSearchProvider, poor_sources: list[Source]
    ) -> None:
        # Return sources with URLs that already exist
        mock_search.set_results([
            _make_source("https://ru.wikipedia.org/1", "Duplicate"),
            _make_source("https://new-source.ru/fresh", "New one"),
        ])
        checker = SourceDiversityChecker(search=mock_search)
        report = checker.analyze(poor_sources)

        improved = await checker.improve(
            sources=poor_sources, topic="Тема", report=report
        )

        urls = [s.url for s in improved]
        # Original 4 + 1 new (duplicate filtered)
        assert urls.count("https://ru.wikipedia.org/1") == 1
        assert "https://new-source.ru/fresh" in urls

    def test_extract_domain(self, mock_search: MockSearchProvider) -> None:
        checker = SourceDiversityChecker(search=mock_search)
        assert checker._extract_domain("https://www.example.com/path") == "example.com"
        assert checker._extract_domain("http://cyberleninka.ru/article") == "cyberleninka.ru"
        assert checker._extract_domain("https://sub.domain.org") == "sub.domain.org"
