"""Source ranking and deduplication."""

import structlog

from shared.schemas.pipeline import Source

logger = structlog.get_logger()


class SourceRanker:
    """Ranks and deduplicates research sources.

    Scoring heuristics:
    - Relevance score from search provider
    - Content length (longer = more substance, up to a point)
    - Deduplication by URL domain + title similarity
    """

    def __init__(self, min_content_length: int = 200) -> None:
        self._min_content_length = min_content_length

    def rank_and_filter(
        self,
        sources: list[Source],
        max_sources: int = 15,
    ) -> list[Source]:
        """Rank sources by quality and deduplicate.

        Args:
            sources: Raw source list from search + scraping.
            max_sources: Maximum sources to keep.

        Returns:
            Filtered, deduplicated, and ranked source list.
        """
        # Step 1: Remove truly useless sources (no title AND no url)
        # Sources without full_text are kept for bibliography (title+url+snippet)
        # but will score lower in ranking
        filtered = [
            s for s in sources
            if s.title or s.url
        ]

        # Step 2: Deduplicate by URL (normalize)
        seen_urls: set[str] = set()
        deduped = []
        for source in filtered:
            normalized_url = self._normalize_url(source.url)
            if normalized_url not in seen_urls:
                seen_urls.add(normalized_url)
                deduped.append(source)

        # Step 3: Score and rank
        for source in deduped:
            source.relevance_score = self._compute_score(source)

        ranked = sorted(deduped, key=lambda s: s.relevance_score, reverse=True)

        logger.info(
            "ranking_complete",
            input_count=len(sources),
            after_filter=len(filtered),
            after_dedup=len(deduped),
            output_count=min(len(ranked), max_sources),
        )

        return ranked[:max_sources]

    def _compute_score(self, source: Source) -> float:
        """Compute a composite quality score for a source."""
        score = source.relevance_score * 0.5  # Search provider relevance

        # Content length bonus (logarithmic, caps at ~5000 chars)
        text_len = len(source.full_text) if source.full_text else 0
        if text_len > 500:
            length_bonus = min(text_len / 5000, 1.0) * 0.3
            score += length_bonus

        # Academic source bonus
        if source.is_academic:
            score += 0.2

        return min(score, 1.0)

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Normalize URL for deduplication."""
        url = url.lower().rstrip("/")
        for prefix in ("https://www.", "http://www.", "https://", "http://"):
            if url.startswith(prefix):
                url = url[len(prefix):]
                break
        return url
