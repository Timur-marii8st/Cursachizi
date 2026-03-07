"""Source diversity checker — ensures bibliography has enough variety."""

from urllib.parse import urlparse

import structlog

from backend.app.pipeline.research.searcher import SearchProvider
from shared.schemas.pipeline import Source

logger = structlog.get_logger()

# Known academic domains for Russian academic context
ACADEMIC_DOMAINS = {
    "elibrary.ru",
    "cyberleninka.ru",
    "scholar.google.com",
    "sciencedirect.com",
    "springer.com",
    "wiley.com",
    "jstor.org",
    "researchgate.net",
    "arxiv.org",
    "pubmed.ncbi.nlm.nih.gov",
    "dissercat.com",
    "rsl.ru",
}

# Domains that are acceptable but shouldn't dominate
GENERAL_DOMAINS = {
    "wikipedia.org",
    "ru.wikipedia.org",
    "en.wikipedia.org",
}


class DiversityReport:
    """Report on source diversity metrics."""

    def __init__(
        self,
        total_sources: int,
        unique_domains: int,
        academic_count: int,
        wikipedia_count: int,
        needs_more_sources: bool,
        needs_more_academic: bool,
        needs_more_diversity: bool,
    ) -> None:
        self.total_sources = total_sources
        self.unique_domains = unique_domains
        self.academic_count = academic_count
        self.wikipedia_count = wikipedia_count
        self.needs_more_sources = needs_more_sources
        self.needs_more_academic = needs_more_academic
        self.needs_more_diversity = needs_more_diversity

    @property
    def is_sufficient(self) -> bool:
        return not (
            self.needs_more_sources
            or self.needs_more_academic
            or self.needs_more_diversity
        )


class SourceDiversityChecker:
    """Checks and improves source diversity in bibliography."""

    def __init__(
        self,
        search: SearchProvider,
        min_sources: int = 15,
        min_unique_domains: int = 5,
        min_academic_sources: int = 3,
        max_wikipedia_ratio: float = 0.2,
    ) -> None:
        self._search = search
        self._min_sources = min_sources
        self._min_unique_domains = min_unique_domains
        self._min_academic_sources = min_academic_sources
        self._max_wikipedia_ratio = max_wikipedia_ratio

    def analyze(self, sources: list[Source]) -> DiversityReport:
        """Analyze source list for diversity metrics."""
        domains = set()
        academic_count = 0
        wikipedia_count = 0

        for source in sources:
            domain = self._extract_domain(source.url)
            domains.add(domain)

            if self._is_academic(domain):
                academic_count += 1
                source.is_academic = True

            if domain in GENERAL_DOMAINS or "wikipedia" in domain:
                wikipedia_count += 1

        return DiversityReport(
            total_sources=len(sources),
            unique_domains=len(domains),
            academic_count=academic_count,
            wikipedia_count=wikipedia_count,
            needs_more_sources=len(sources) < self._min_sources,
            needs_more_academic=academic_count < self._min_academic_sources,
            needs_more_diversity=len(domains) < self._min_unique_domains,
        )

    async def improve(
        self,
        sources: list[Source],
        topic: str,
        report: DiversityReport,
        max_additional_searches: int = 3,
    ) -> list[Source]:
        """Run additional searches to improve diversity if needed.

        Returns augmented source list.
        """
        if report.is_sufficient:
            return sources

        additional: list[Source] = []

        if report.needs_more_academic:
            # Search specifically for academic sources
            academic_queries = [
                f"{topic} site:cyberleninka.ru",
                f"{topic} site:elibrary.ru",
                f"{topic} научная статья",
            ]
            for query in academic_queries[:max_additional_searches]:
                try:
                    results = await self._search.search(query, max_results=5)
                    additional.extend(results)
                except Exception as e:
                    logger.warning("diversity_search_failed", query=query, error=str(e))

        elif report.needs_more_sources or report.needs_more_diversity:
            # Broader search for more diverse sources
            diverse_queries = [
                f"{topic} исследование",
                f"{topic} монография",
                f"{topic} учебное пособие",
            ]
            for query in diverse_queries[:max_additional_searches]:
                try:
                    results = await self._search.search(query, max_results=5)
                    additional.extend(results)
                except Exception as e:
                    logger.warning("diversity_search_failed", query=query, error=str(e))

        # Deduplicate by URL
        existing_urls = {s.url for s in sources}
        new_sources = [s for s in additional if s.url not in existing_urls]

        combined = sources + new_sources
        logger.info(
            "diversity_improved",
            original=len(sources),
            added=len(new_sources),
            total=len(combined),
        )

        return combined

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extract the domain from a URL."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except Exception:
            return url

    @staticmethod
    def _is_academic(domain: str) -> bool:
        """Check if domain is a known academic source."""
        return any(
            academic in domain
            for academic in ACADEMIC_DOMAINS
        )
