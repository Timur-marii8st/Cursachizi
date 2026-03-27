"""Pipeline-internal schemas for data flowing between stages."""

from datetime import date
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, Field, PrivateAttr


def _coerce_int(v: object) -> int:
    """Round floats to int — LLM sometimes returns 1.2 instead of 1."""
    if isinstance(v, float):
        return round(v)
    return v  # type: ignore[return-value]


CoercedInt = Annotated[int, BeforeValidator(_coerce_int)]

CHAPTER_INTRO: int = 0
CHAPTER_CONCLUSION: int = 99


class Source(BaseModel):
    """A research source found during the deep research stage."""

    url: str
    title: str
    snippet: str = ""
    full_text: str = ""
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    is_academic: bool = False
    language: str = "ru"


class ResearchResult(BaseModel):
    """Output of the deep research stage."""

    original_topic: str
    expanded_queries: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    key_concepts: list[str] = Field(default_factory=list)
    summary: str = ""


class OutlineChapter(BaseModel):
    """A single chapter in the coursework outline."""

    number: int
    title: str
    subsections: list[str] = Field(default_factory=list)
    description: str = ""
    estimated_pages: CoercedInt = 3


class Outline(BaseModel):
    """Complete coursework or article outline."""

    title: str
    introduction_points: list[str] = Field(default_factory=list)
    chapters: list[OutlineChapter] = Field(default_factory=list)
    conclusion_points: list[str] = Field(default_factory=list)
    # Article-specific fields
    keywords: list[str] = Field(default_factory=list)
    abstract_points: list[str] = Field(default_factory=list)


class BibliographyEntry(BaseModel):
    """A single entry in the unified bibliography registry.

    Built from real research sources — never hallucinated by LLM.
    """

    number: int
    title: str
    url: str = ""
    formatted_reference: str


class BibliographyRegistry(BaseModel):
    """Unified numbered bibliography built from real research sources.

    Created after the research stage and passed to all section writers
    so that inline citations [N] reference real, verified sources.
    """

    entries: list[BibliographyEntry] = Field(default_factory=list)

    # Private cache attributes — not serialized, rebuilt lazily as needed.
    _entry_index_cache: dict[int, "BibliographyEntry"] = PrivateAttr(default_factory=dict)
    _entry_index_len: int = PrivateAttr(default=0)
    _format_cache: str = PrivateAttr(default="")
    _format_cache_key: tuple[int, int] = PrivateAttr(default=(-1, -1))

    @classmethod
    def from_sources(cls, sources: list["Source"]) -> "BibliographyRegistry":
        """Build a registry from research sources, deduplicating by URL or title."""
        seen_urls: set[str] = set()
        seen_titles: set[str] = set()
        unique_sources: list[Source] = []
        for source in sources:
            if source.url:
                if source.url in seen_urls:
                    continue
                seen_urls.add(source.url)
            else:
                normalized = source.title.strip().lower()
                if normalized in seen_titles:
                    continue
                seen_titles.add(normalized)
            unique_sources.append(source)

        entries = []
        today = date.today().strftime("%d.%m.%Y")
        for i, source in enumerate(unique_sources, 1):
            if source.url:
                ref = (
                    f"{source.title} [Электронный ресурс]. "
                    f"— URL: {source.url} (дата обращения: {today})"
                )
            else:
                ref = f"{source.title}."
            entries.append(BibliographyEntry(
                number=i,
                title=source.title,
                url=source.url,
                formatted_reference=ref,
            ))
        return cls(entries=entries)

    def format_for_prompt(self, max_entries: int | None = None) -> str:
        """Format registry for inclusion in LLM prompts.

        Shows all entries with their global numbers so LLM can cite them.
        """
        entries = self.entries[:max_entries] if max_entries else self.entries
        if not entries:
            return "Источники не найдены."
        lines = []
        for entry in entries:
            lines.append(f"[{entry.number}] {entry.formatted_reference}")
        return "\n".join(lines)

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Normalize a URL for consistent lookup matching.

        Strips scheme, www prefix, trailing slashes, and lowercases so that
        URLs stored in the registry (original form) and URLs that went through
        the Ranker's normalization always produce the same key.
        """
        url = url.lower().strip().rstrip("/")
        for prefix in ("https://", "http://", "www."):
            if url.startswith(prefix):
                url = url[len(prefix):]
        return url

    def format_with_content(
        self, sources: list["Source"], max_content_entries: int = 15
    ) -> str:
        """Format registry with source content for section writing prompts.

        Includes full text/snippet for the first N sources so LLM has context.
        All source numbers are shown so LLM can cite any of them.

        URLs are normalized before building the lookup dict so that sources
        whose URLs were transformed by the Ranker (lowercased, scheme stripped,
        trailing slash removed) still match their registry entries.
        """
        if not self.entries:
            return "Источники не предоставлены."

        # Build lookup: normalized_url → source (primary), title → source (fallback)
        by_url: dict[str, Source] = {}
        by_title: dict[str, Source] = {}
        for source in sources:
            if source.url:
                by_url[self._normalize_url(source.url)] = source
            title_key = source.title.strip().lower()
            if title_key not in by_title:
                by_title[title_key] = source

        lines = []
        content_count = 0
        for entry in self.entries:
            # Look up source by normalized URL first, then by title
            source = by_url.get(self._normalize_url(entry.url)) if entry.url else None
            if source is None:
                source = by_title.get(entry.title.strip().lower())

            if source and content_count < max_content_entries:
                text = source.full_text[:1500] if source.full_text else source.snippet
                if text:
                    lines.append(f"[{entry.number}] {entry.title}\n{text}\n")
                    content_count += 1
                else:
                    lines.append(f"[{entry.number}] {entry.title}")
            else:
                lines.append(f"[{entry.number}] {entry.title}")
        return "\n".join(lines)

    def get_formatted_content_cached(
        self, sources: list["Source"], max_content_entries: int = 15
    ) -> str:
        """Like format_with_content() but caches the result.

        The cache key is based on the identity of the sources list object and
        max_content_entries. The cache is invalidated when the sources list
        object changes or max_content_entries differs. This avoids rebuilding
        the full lookup dict and formatting all entries on every section write
        call (typically 15 calls per pipeline run).
        """
        cache_key = (id(sources), max_content_entries)
        if self._format_cache_key != cache_key:
            self._format_cache = self.format_with_content(sources, max_content_entries)
            self._format_cache_key = cache_key
        return self._format_cache

    @property
    def _entry_index(self) -> dict[int, "BibliographyEntry"]:
        """Lazy-built O(1) index from entry number to BibliographyEntry.

        Rebuilt only when the number of entries has changed (entries were added
        or removed). Using entry count as a cheap staleness signal avoids a
        full equality check on every access.
        """
        if self._entry_index_len != len(self.entries):
            self._entry_index_cache = {e.number: e for e in self.entries}
            self._entry_index_len = len(self.entries)
        return self._entry_index_cache

    def get_entry(self, number: int) -> "BibliographyEntry | None":
        """Get entry by its global number in O(1) via a cached index."""
        return self._entry_index.get(number)

    def validate_citations(self, text: str) -> list[int]:
        """Find citation numbers in text that don't exist in the registry."""
        import re
        cited = set(int(m) for m in re.findall(r"\[(\d+)\]", text))
        valid = set(e.number for e in self.entries)
        return sorted(cited - valid)


class SectionContent(BaseModel):
    """Generated content for a single section."""

    chapter_number: int
    section_title: str
    content: str
    citations: list[str] = Field(default_factory=list)
    word_count: int = 0


class ClaimVerdict(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNCERTAIN = "uncertain"


class FactCheckClaim(BaseModel):
    """A single factual claim extracted from generated text."""

    claim_text: str
    source_section: str
    verdict: ClaimVerdict = ClaimVerdict.UNCERTAIN
    evidence: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    correction: str | None = None


class FactCheckResult(BaseModel):
    """Output of the fact verification stage."""

    total_claims: int = 0
    checked_claims: int = 0
    supported: int = 0
    unsupported: int = 0
    uncertain: int = 0
    claims: list[FactCheckClaim] = Field(default_factory=list)
    corrections_applied: int = 0


class VisualMatchResult(BaseModel):
    """Result of a single visual template matching iteration."""

    iteration: int
    score: float = Field(default=0.0, ge=0.0, le=10.0)
    issues: list[str] = Field(default_factory=list)
    fixes_applied: list[str] = Field(default_factory=list)
    converged: bool = False


class CoherenceIssue(BaseModel):
    """A single coherence issue found between sections."""

    issue_type: str  # terminology | contradiction | missing_reference | logic_gap
    description: str
    section_a: str = ""
    section_b: str = ""
    suggestion: str = ""


class CoherenceResult(BaseModel):
    """Output of the cross-section coherence check."""

    issues_found: int = 0
    issues: list[CoherenceIssue] = Field(default_factory=list)
    fixes_applied: int = 0
    sections_modified: list[str] = Field(default_factory=list)


class SectionEvaluation(BaseModel):
    """Evaluation of a single section's quality."""

    section_title: str
    passed: bool = True
    word_count_ok: bool = True
    citations_ok: bool = True
    no_duplication: bool = True
    style_ok: bool = True
    feedback: str = ""
    rewrite_count: int = 0


class ComplianceIssue(BaseModel):
    """A single issue found by the outline compliance checker."""

    section_title: str
    chapter_number: int
    issue_type: str  # "off_topic" | "missing_content" | "insufficient_sources"
    description: str
    suggestion: str = ""


class ComplianceResult(BaseModel):
    """Result of outline compliance check."""

    issues: list[ComplianceIssue] = Field(default_factory=list)
    sections_checked: int = 0
    sections_compliant: int = 0

    @property
    def is_compliant(self) -> bool:
        return len(self.issues) == 0


class PipelineConfig(BaseModel):
    """Configuration for a single pipeline run."""

    max_search_results: int = Field(default=60, ge=5, le=200)
    max_sources: int = Field(default=30, ge=5, le=80)
    max_tokens_per_section: int = Field(default=4000, ge=1000, le=8000)
    enable_fact_check: bool = True
    max_claims_per_chapter: int = Field(default=5, ge=1, le=20)
    writer_model: str = "google/google/gemini-3.1-flash-lite-preview"
    light_model: str = "stepfun/step-3.5-flash"
    vision_model: str = "google/google/gemini-3.1-flash-lite-preview"
    search_provider: str = "duckduckgo"
    timeout_seconds: int = Field(default=900, ge=120, le=3600)

    # Visual template matching
    enable_visual_match: bool = True
    visual_match_max_iterations: int = Field(default=3, ge=1, le=10)

    # Iterative fact-checking
    fact_check_max_rounds: int = Field(default=2, ge=1, le=5)

    # Quality improvement agents (Phase 2)
    enable_coherence_check: bool = True
    enable_section_rewrite: bool = True
    max_section_rewrites: int = Field(default=2, ge=0, le=5)
    min_citations_per_section: int = Field(default=4, ge=0, le=15)
    enable_humanizer: bool = False

    # Outline compliance checking (for custom outlines)
    enable_outline_compliance: bool = True
    max_compliance_iterations: int = Field(default=2, ge=1, le=4)
