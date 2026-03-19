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

REFINE_SEARCH_PROMPT = """Предыдущий поиск по утверждению не дал убедительного результата.

УТВЕРЖДЕНИЕ: {claim}
ПРЕДЫДУЩИЙ ЗАПРОС: {previous_query}
ПРЕДЫДУЩИЙ РЕЗУЛЬТАТ: {previous_verdict} (уверенность: {confidence})

Сформулируй ДРУГОЙ поисковый запрос, чтобы найти более точные источники.
Попробуй другие ключевые слова, синонимы или более конкретную формулировку.

Ответь ТОЛЬКО поисковым запросом, без пояснений."""


class FactChecker:
    """Verifies individual claims by searching and evaluating evidence.

    Supports iterative verification: if the first search round yields
    uncertain results (low confidence), the checker reformulates the search
    query and tries again, up to max_rounds times.
    """

    def __init__(self, llm: LLMProvider, search: SearchProvider) -> None:
        self._llm = llm
        self._search = search

    async def check_claim(
        self,
        claim: FactCheckClaim,
        model: str | None = None,
        max_rounds: int = 1,
    ) -> FactCheckClaim:
        """Verify a single claim with iterative search-verify cycles.

        Args:
            claim: The claim to check.
            model: LLM model override.
            max_rounds: Max search-verify rounds (1 = original single-pass behavior).

        Returns the claim with verdict, evidence, and confidence filled in.
        """
        query = claim.claim_text

        for round_num in range(1, max_rounds + 1):
            search_results = await self._search.search(query=query, max_results=3)

            if not search_results:
                claim.verdict = ClaimVerdict.UNCERTAIN
                claim.confidence = 0.0
                claim.evidence = "Не удалось найти источники для проверки."
                logger.warning(
                    "claim_check_no_search_results",
                    claim=claim.claim_text[:60],
                    round=round_num,
                )
                return claim

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

            self._parse_verdict(response.content, claim)

            logger.info(
                "claim_checked",
                claim=claim.claim_text[:60],
                verdict=claim.verdict,
                confidence=claim.confidence,
                round=round_num,
            )

            # Stop if confident or definitively supported/unsupported
            if claim.confidence >= 0.7 or claim.verdict != ClaimVerdict.UNCERTAIN:
                break

            # Reformulate query for next round
            if round_num < max_rounds:
                logger.info("reformulating_search", round=round_num)
                query = await self._reformulate_query(
                    claim.claim_text, query,
                    claim.verdict.value, claim.confidence, model,
                )

        return claim

    async def _reformulate_query(
        self,
        original_claim: str,
        previous_query: str,
        previous_verdict: str,
        confidence: float,
        model: str | None = None,
    ) -> str:
        """Ask the LLM to reformulate the search query for the next round."""
        prompt = REFINE_SEARCH_PROMPT.format(
            claim=original_claim,
            previous_query=previous_query,
            previous_verdict=previous_verdict,
            confidence=confidence,
        )

        response = await self._llm.generate(
            messages=[LLMMessage(role="user", content=prompt)],
            model=model,
            temperature=0.5,
            max_tokens=100,
        )

        new_query = response.content.strip().strip('"').strip("'")
        return new_query if new_query else original_claim

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
