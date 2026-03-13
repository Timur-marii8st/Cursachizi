"""Pipeline-internal schemas for data flowing between stages."""

from enum import StrEnum

from pydantic import BaseModel, Field

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
    estimated_pages: int = 3


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

    @classmethod
    def from_sources(cls, sources: list["Source"]) -> "BibliographyRegistry":
        """Build a registry from research sources, deduplicating by URL."""
        seen_urls: set[str] = set()
        unique_sources: list[Source] = []
        for source in sources:
            if source.url and source.url in seen_urls:
                continue
            if source.url:
                seen_urls.add(source.url)
            unique_sources.append(source)

        entries = []
        for i, source in enumerate(unique_sources, 1):
            ref = source.title
            if source.url:
                ref += f" [Электронный ресурс]. — URL: {source.url}"
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

    def format_with_content(
        self, sources: list["Source"], max_content_entries: int = 8
    ) -> str:
        """Format registry with source content for section writing prompts.

        Includes full text/snippet for the first N sources so LLM has context.
        All source numbers are shown so LLM can cite any of them.
        """
        if not self.entries:
            return "Источники не предоставлены."
        lines = []
        content_count = 0
        for entry in self.entries:
            # Match by position: entry.number is 1-based index into original sources list
            source_idx = entry.number - 1
            source = sources[source_idx] if 0 <= source_idx < len(sources) else None
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

    def get_entry(self, number: int) -> BibliographyEntry | None:
        """Get entry by its global number."""
        for entry in self.entries:
            if entry.number == number:
                return entry
        return None

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


class PipelineConfig(BaseModel):
    """Configuration for a single pipeline run."""

    max_search_results: int = Field(default=20, ge=5, le=50)
    max_sources: int = Field(default=15, ge=5, le=30)
    max_tokens_per_section: int = Field(default=4000, ge=1000, le=8000)
    enable_fact_check: bool = True
    max_claims_per_chapter: int = Field(default=5, ge=1, le=20)
    writer_model: str = "google/google/gemini-3.1-flash-lite-preview"
    light_model: str = "stepfun/step-3.5-flash"
    vision_model: str = "google/google/gemini-3.1-flash-lite-preview"
    search_provider: str = "tavily"
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
    min_citations_per_section: int = Field(default=2, ge=0, le=10)
    enable_humanizer: bool = False
