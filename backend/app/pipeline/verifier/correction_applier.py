"""Apply fact-check corrections to section text via targeted sentence replacement."""

import re

import structlog

from backend.app.llm.provider import LLMMessage, LLMProvider
from shared.schemas.pipeline import FactCheckClaim, FactCheckResult, SectionContent

logger = structlog.get_logger()

CORRECTION_PROMPT = """Ты — научный редактор. Перепиши ОДНО предложение, исправив фактическую неточность.

ИСХОДНОЕ ПРЕДЛОЖЕНИЕ:
{original_sentence}

НЕТОЧНОЕ УТВЕРЖДЕНИЕ В НЁМ:
{claim_text}

ПРЕДЛОЖЕННОЕ ИСПРАВЛЕНИЕ:
{correction}

КОНТЕКСТ (предыдущее и следующее предложения):
{context}

ТРЕБОВАНИЯ:
1. Перепиши ТОЛЬКО это предложение — сохрани стиль, длину и тон
2. Исправь фактическую неточность согласно предложенному исправлению
3. Сохрани все ссылки на источники [N] если они есть
4. НЕ добавляй markdown-разметку
5. НЕ добавляй пояснений — верни ТОЛЬКО исправленное предложение

ИСПРАВЛЕННОЕ ПРЕДЛОЖЕНИЕ:"""


class CorrectionApplier:
    """Applies fact-check corrections to sections by replacing inaccurate sentences."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def apply_corrections(
        self,
        sections: list[SectionContent],
        fact_check: FactCheckResult,
        model: str | None = None,
    ) -> tuple[list[SectionContent], int]:
        """Apply corrections from fact-check results to section texts.

        Args:
            sections: Written sections to correct.
            fact_check: Fact-check result with claims and corrections.
            model: LLM model for rewriting sentences.

        Returns:
            Tuple of (updated sections, number of corrections applied).
        """
        # Collect claims that need correction
        claims_to_fix = [
            c for c in fact_check.claims
            if c.correction is not None and c.correction.strip()
        ]

        if not claims_to_fix:
            logger.info("no_corrections_to_apply")
            return sections, 0

        logger.info("applying_corrections", count=len(claims_to_fix))

        applied = 0
        for claim in claims_to_fix:
            section = self._find_section(sections, claim)
            if section is None:
                logger.warning(
                    "section_not_found_for_claim",
                    claim=claim.claim_text[:60],
                    source_section=claim.source_section,
                )
                continue

            sentence = self._find_sentence(section.content, claim.claim_text)
            if sentence is None:
                logger.warning(
                    "sentence_not_found",
                    claim=claim.claim_text[:60],
                    section=section.section_title[:40],
                )
                continue

            corrected = await self._rewrite_sentence(
                original_sentence=sentence,
                claim=claim,
                full_text=section.content,
                model=model,
            )

            if corrected and corrected != sentence:
                section.content = section.content.replace(sentence, corrected, 1)
                section.word_count = len(section.content.split())
                applied += 1
                logger.info(
                    "correction_applied",
                    section=section.section_title[:40],
                    claim=claim.claim_text[:60],
                )

        logger.info("corrections_complete", applied=applied, total=len(claims_to_fix))
        return sections, applied

    @staticmethod
    def _find_section(
        sections: list[SectionContent], claim: FactCheckClaim,
    ) -> SectionContent | None:
        """Find the section containing the claim."""
        # First try exact title match
        for section in sections:
            if section.section_title == claim.source_section:
                return section

        # Fallback: search all sections for claim text
        for section in sections:
            if claim.claim_text[:40].lower() in section.content.lower():
                return section

        return None

    @staticmethod
    def _find_sentence(text: str, claim_text: str) -> str | None:
        """Find the sentence in text that contains the claim.

        Uses progressive fuzzy matching:
        1. Try to find a sentence containing the full claim text
        2. Try with key phrases (numbers, names) from the claim
        """
        sentences = re.split(r'(?<=[.!?])\s+', text)

        # Strategy 1: direct substring match (case-insensitive)
        claim_lower = claim_text.lower()
        for sentence in sentences:
            if claim_lower in sentence.lower():
                return sentence

        # Strategy 2: match by key tokens (numbers, capitalized words)
        key_tokens = re.findall(r'\d+[%,.]?\d*|\b[А-ЯA-Z][а-яa-z]+(?:\s+[А-ЯA-Z][а-яa-z]+)*', claim_text)
        if key_tokens:
            best_match = None
            best_score = 0
            for sentence in sentences:
                score = sum(1 for token in key_tokens if token in sentence)
                if score > best_score:
                    best_score = score
                    best_match = sentence
            # Require at least half of key tokens to match
            if best_match and best_score >= max(1, len(key_tokens) // 2):
                return best_match

        return None

    async def _rewrite_sentence(
        self,
        original_sentence: str,
        claim: FactCheckClaim,
        full_text: str,
        model: str | None = None,
    ) -> str | None:
        """Ask LLM to rewrite a sentence with the correction applied."""
        context = self._get_context(full_text, original_sentence)

        prompt = CORRECTION_PROMPT.format(
            original_sentence=original_sentence,
            claim_text=claim.claim_text,
            correction=claim.correction,
            context=context,
        )

        try:
            response = await self._llm.generate(
                messages=[LLMMessage(role="user", content=prompt)],
                model=model,
                temperature=0.3,
                max_tokens=500,
            )
            corrected = response.content.strip()
            # Sanity check: corrected sentence should be reasonable length
            if len(corrected) < 10 or len(corrected) > len(original_sentence) * 3:
                logger.warning(
                    "correction_rejected_bad_length",
                    original_len=len(original_sentence),
                    corrected_len=len(corrected),
                )
                return None
            return corrected
        except Exception as e:
            logger.error("correction_rewrite_failed", error=str(e))
            return None

    @staticmethod
    def _get_context(full_text: str, sentence: str, window: int = 1) -> str:
        """Get surrounding sentences for context."""
        sentences = re.split(r'(?<=[.!?])\s+', full_text)
        try:
            idx = next(i for i, s in enumerate(sentences) if sentence in s)
        except StopIteration:
            return ""

        start = max(0, idx - window)
        end = min(len(sentences), idx + window + 1)

        context_parts = []
        for i in range(start, end):
            if i == idx:
                context_parts.append(f">>> {sentences[i]} <<<")
            else:
                context_parts.append(sentences[i])

        return " ".join(context_parts)
