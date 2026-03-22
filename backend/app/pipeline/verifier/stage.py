"""Complete fact verification stage."""

import asyncio

import structlog

from backend.app.llm.provider import LLMProvider
from backend.app.pipeline.research.searcher import SearchProvider
from backend.app.pipeline.verifier.claim_extractor import ClaimExtractor
from backend.app.pipeline.verifier.fact_checker import FactChecker
from shared.schemas.pipeline import (
    CHAPTER_CONCLUSION,
    CHAPTER_INTRO,
    ClaimVerdict,
    FactCheckResult,
    PipelineConfig,
    SectionContent,
)

logger = structlog.get_logger()


class VerifierStage:
    """Orchestrates claim extraction and fact-checking across all sections."""

    def __init__(self, llm: LLMProvider, search: SearchProvider) -> None:
        self._claim_extractor = ClaimExtractor(llm)
        self._fact_checker = FactChecker(llm, search)

    async def run(
        self,
        sections: list[SectionContent],
        config: PipelineConfig | None = None,
        progress_callback=None,
    ) -> FactCheckResult:
        """Run fact verification on all sections.

        Args:
            sections: Written sections to verify.
            config: Pipeline configuration.
            progress_callback: Optional async callback(claims_checked, total_claims).

        Returns:
            FactCheckResult with all claims and verdicts.
        """
        config = config or PipelineConfig()

        if not config.enable_fact_check:
            logger.info("fact_checking_disabled")
            return FactCheckResult()

        result = FactCheckResult()

        # Step 1: Extract claims from each section
        all_claims = []
        for section in sections:
            # Skip intro/conclusion from fact-checking
            if section.chapter_number in (CHAPTER_INTRO, CHAPTER_CONCLUSION):
                continue

            claims = await self._claim_extractor.extract(
                text=section.content,
                section_title=section.section_title,
                max_claims=config.max_claims_per_chapter,
                model=config.light_model,
            )
            all_claims.extend(claims)

        result.total_claims = len(all_claims)
        logger.info("total_claims_extracted", count=len(all_claims))

        # Step 2: Fact-check claims in parallel.
        # Semaphore=5 — fact-checking is lighter than writing so higher concurrency is safe.
        claim_semaphore = asyncio.Semaphore(5)

        async def check_one(claim):
            async with claim_semaphore:
                return await self._fact_checker.check_claim(
                    claim=claim,
                    model=config.light_model,
                    max_rounds=config.fact_check_max_rounds,
                )

        check_tasks = [check_one(c) for c in all_claims]
        # return_exceptions=True so a single failing claim doesn't abort the rest
        checked_results = await asyncio.gather(*check_tasks, return_exceptions=True)

        checked_count = 0
        for i, checked in enumerate(checked_results):
            if isinstance(checked, Exception):
                logger.warning(
                    "claim_check_failed",
                    claim_index=i,
                    error=str(checked),
                )
                continue

            result.claims.append(checked)
            checked_count += 1
            result.checked_claims = checked_count

            if checked.verdict == ClaimVerdict.SUPPORTED:
                result.supported += 1
            elif checked.verdict == ClaimVerdict.UNSUPPORTED:
                result.unsupported += 1
            else:
                result.uncertain += 1

            if progress_callback:
                await progress_callback(result.checked_claims, result.total_claims)

        # Count corrections
        result.corrections_applied = sum(
            1 for c in result.claims if c.correction is not None
        )

        logger.info(
            "fact_check_complete",
            total=result.total_claims,
            supported=result.supported,
            unsupported=result.unsupported,
            uncertain=result.uncertain,
            corrections=result.corrections_applied,
        )

        return result
