"""Fact-checking individual claims against web search results."""

import structlog

from backend.app.llm.provider import LLMMessage, LLMProvider
from backend.app.pipeline.research.searcher import SearchProvider
from shared.schemas.pipeline import ClaimVerdict, FactCheckClaim

logger = structlog.get_logger()

VERDICT_PROMPT = """Ты — факт-чекер. Оцени, подтверждается ли следующее утверждение найденными источниками.

УТВЕРЖДЕНИЕ: {claim}

НАЙДЕННЫЕ ИСТОЧНИКИ:
{search_results}

Оцени утверждение:
- "supported" — если источники подтверждают утверждение
- "unsupported" — если источники опровергают утверждение или содержат противоречащую информацию
- "uncertain" — если источники не содержат достаточно информации

Ответь в формате:
VERDICT: supported/unsupported/uncertain
CONFIDENCE: 0.0-1.0
EVIDENCE: краткое обоснование (1-2 предложения)
CORRECTION: если unsupported, предложи исправление (или "нет")"""


class FactChecker:
    """Verifies individual claims by searching and evaluating evidence."""

    def __init__(self, llm: LLMProvider, search: SearchProvider) -> None:
        self._llm = llm
        self._search = search

    async def check_claim(
        self,
        claim: FactCheckClaim,
        model: str | None = None,
    ) -> FactCheckClaim:
        """Verify a single claim against web search results.

        Searches for the claim, then uses an LLM to evaluate whether
        search results support, refute, or are inconclusive about the claim.

        Returns the claim with verdict, evidence, and confidence filled in.
        """
        # Search for evidence
        search_results = await self._search.search(
            query=claim.claim_text,
            max_results=3,
        )

        if not search_results:
            claim.verdict = ClaimVerdict.UNCERTAIN
            claim.confidence = 0.0
            claim.evidence = "Не удалось найти источники для проверки."
            return claim

        # Format search results for the LLM
        results_text = "\n\n".join(
            f"[{i}] {r.title}\n{r.snippet or r.full_text[:500]}"
            for i, r in enumerate(search_results, 1)
        )

        prompt = VERDICT_PROMPT.format(
            claim=claim.claim_text,
            search_results=results_text,
        )

        response = await self._llm.generate(
            messages=[LLMMessage(role="user", content=prompt)],
            model=model,
            temperature=0.2,
            max_tokens=512,
        )

        # Parse the response
        self._parse_verdict(response.content, claim)

        logger.info(
            "claim_checked",
            claim=claim.claim_text[:60],
            verdict=claim.verdict,
            confidence=claim.confidence,
        )

        return claim

    @staticmethod
    def _parse_verdict(response_text: str, claim: FactCheckClaim) -> None:
        """Parse structured verdict response into the claim object."""
        lines = response_text.strip().split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith("VERDICT:"):
                verdict_str = line.split(":", 1)[1].strip().lower()
                if verdict_str in ("supported", "unsupported", "uncertain"):
                    claim.verdict = ClaimVerdict(verdict_str)
            elif line.startswith("CONFIDENCE:"):
                try:
                    claim.confidence = float(line.split(":", 1)[1].strip())
                except ValueError:
                    claim.confidence = 0.5
            elif line.startswith("EVIDENCE:"):
                claim.evidence = line.split(":", 1)[1].strip()
            elif line.startswith("CORRECTION:"):
                correction = line.split(":", 1)[1].strip()
                if correction.lower() not in ("нет", "no", "none", "-"):
                    claim.correction = correction
