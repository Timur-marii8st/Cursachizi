"""Pipeline-internal schemas for data flowing between stages."""

from enum import StrEnum

from pydantic import BaseModel, Field, HttpUrl


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
    """Complete coursework outline."""

    title: str
    introduction_points: list[str] = Field(default_factory=list)
    chapters: list[OutlineChapter] = Field(default_factory=list)
    conclusion_points: list[str] = Field(default_factory=list)


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


class PipelineConfig(BaseModel):
    """Configuration for a single pipeline run."""

    max_search_results: int = Field(default=20, ge=5, le=50)
    max_sources: int = Field(default=15, ge=5, le=30)
    max_tokens_per_section: int = Field(default=4000, ge=1000, le=8000)
    enable_fact_check: bool = True
    max_claims_per_chapter: int = Field(default=5, ge=1, le=20)
    writer_model: str = "claude-sonnet-4-5-20241022"
    light_model: str = "claude-haiku-4-5-20241022"
    search_provider: str = "tavily"
    timeout_seconds: int = Field(default=900, ge=120, le=3600)
