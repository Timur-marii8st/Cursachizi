"""Extract verifiable factual claims from generated text."""

import json

import structlog

from backend.app.llm.provider import LLMMessage, LLMProvider
from shared.schemas.pipeline import FactCheckClaim

logger = structlog.get_logger()

CLAIM_EXTRACTION_PROMPT = """Извлеки из текста конкретные фактические утверждения, которые можно проверить.

ТЕКСТ РАЗДЕЛА «{section_title}»:
{text}

Извлеки только утверждения, содержащие:
- Числовые данные (статистика, даты, проценты)
- Конкретные факты (события, открытия, законы)
- Атрибуции (кто что сказал/открыл/разработал)
- Причинно-следственные связи, которые можно верифицировать

НЕ извлекай:
- Общие утверждения и мнения
- Определения терминов
- Очевидные факты

Верни JSON:
{{"claims": [
  {{"claim_text": "конкретное утверждение", "source_section": "{section_title}"}}
]}}

Максимум {max_claims} утверждений. Выбери самые важные и проверяемые."""


class ClaimExtractor:
    """Extracts verifiable factual claims from text using an LLM."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def extract(
        self,
        text: str,
        section_title: str,
        max_claims: int = 5,
        model: str | None = None,
    ) -> list[FactCheckClaim]:
        """Extract factual claims from a section of text.

        Args:
            text: The section text to analyze.
            section_title: Title of the section (for tracking).
            max_claims: Maximum number of claims to extract.
            model: Model override (use lighter model for cost savings).

        Returns:
            List of extracted claims (unverified).
        """
        # Skip very short sections
        if len(text.split()) < 50:
            return []

        prompt = CLAIM_EXTRACTION_PROMPT.format(
            section_title=section_title,
            text=text[:3000],  # Limit input size
            max_claims=max_claims,
        )

        response = await self._llm.generate(
            messages=[LLMMessage(role="user", content=prompt)],
            model=model,
            temperature=0.2,
            max_tokens=1024,
        )

        try:
            content = response.content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1]).strip()
            data = json.loads(content)

            claims = [
                FactCheckClaim(
                    claim_text=c["claim_text"],
                    source_section=c.get("source_section", section_title),
                )
                for c in data.get("claims", [])[:max_claims]
            ]

            logger.info(
                "claims_extracted",
                section=section_title[:50],
                count=len(claims),
            )
            return claims

        except (json.JSONDecodeError, KeyError) as e:
            logger.error("claim_extraction_failed", error=str(e))
            return []
