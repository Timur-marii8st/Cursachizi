"""Humanizer — reduces AI-detectability via translation cycling.

Strategy (based on proven approach):
1. Translate section text through a chain of languages: RU → EN → DE → RU
2. The round-trip translation breaks characteristic AI patterns
3. Use LLM to clean up grammatical/stylistic artifacts from translation
"""

import structlog

from backend.app.llm.provider import LLMMessage, LLMProvider
from shared.schemas.pipeline import SectionContent

logger = structlog.get_logger()

CLEANUP_PROMPT = """Ты — редактор научных текстов на русском языке.

Следующий текст был переведён и содержит стилистические шероховатости. Исправь его:
1. Исправь грамматические ошибки
2. Восстанови академический стиль (третье лицо, безличные конструкции)
3. Сохрани все числа, факты и ссылки на источники [N] в точности
4. НЕ переписывай текст полностью — только устрани неестественные формулировки
5. Сохрани структуру абзацев
6. Объём текста не должен существенно измениться

ТЕКСТ:
{text}

Напиши ТОЛЬКО исправленный текст."""


class TranslationProvider:
    """Abstract interface for translation services."""

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        raise NotImplementedError


class GoogleTranslateProvider(TranslationProvider):
    """Google Cloud Translation API provider."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://translation.googleapis.com/language/translate/v2",
                params={"key": self._api_key},
                json={
                    "q": text,
                    "source": source_lang,
                    "target": target_lang,
                    "format": "text",
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["data"]["translations"][0]["translatedText"]


class DeepLTranslateProvider(TranslationProvider):
    """DeepL API translation provider."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        import httpx

        # DeepL uses uppercase lang codes and specific variants
        lang_map = {"ru": "RU", "en": "EN", "de": "DE", "fr": "FR", "zh": "ZH"}
        target_code = lang_map.get(target_lang, target_lang.upper())
        # DeepL target EN needs to be EN-US or EN-GB
        if target_code == "EN":
            target_code = "EN-US"

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://api-free.deepl.com/v2/translate",
                headers={"Authorization": f"DeepL-Auth-Key {self._api_key}"},
                data={
                    "text": text,
                    "source_lang": lang_map.get(source_lang, source_lang.upper()),
                    "target_lang": target_code,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["translations"][0]["text"]


class Humanizer:
    """Reduces AI-detectability by cycling text through translation APIs
    and then cleaning up with LLM."""

    def __init__(
        self,
        llm: LLMProvider,
        translator: TranslationProvider,
        language_chain: list[str] | None = None,
    ) -> None:
        self._llm = llm
        self._translator = translator
        # Default chain: RU → EN → DE → RU
        self._chain = language_chain or ["ru", "en", "de", "ru"]

    async def humanize_section(
        self,
        section: SectionContent,
        model: str | None = None,
    ) -> SectionContent:
        """Humanize a single section via translation cycling + LLM cleanup."""
        text = section.content

        # Step 1: Translation cycling
        try:
            cycled_text = await self._cycle_through_languages(text)
        except Exception as e:
            logger.warning(
                "translation_cycling_failed",
                section=section.section_title[:50],
                error=str(e),
            )
            # If translation fails, skip humanization for this section
            return section

        # Step 2: LLM cleanup — fix grammar/style artifacts
        response = await self._llm.generate(
            messages=[LLMMessage(
                role="user",
                content=CLEANUP_PROMPT.format(text=cycled_text),
            )],
            model=model,
            temperature=0.3,
            max_tokens=4000,
        )

        cleaned = response.content.strip()
        if not cleaned:
            return section

        import re
        citations = list(set(re.findall(r"\[(\d+)\]", cleaned)))

        logger.info(
            "section_humanized",
            section=section.section_title[:50],
            original_words=section.word_count,
            new_words=len(cleaned.split()),
        )

        return SectionContent(
            chapter_number=section.chapter_number,
            section_title=section.section_title,
            content=cleaned,
            citations=citations,
            word_count=len(cleaned.split()),
        )

    async def humanize_all(
        self,
        sections: list[SectionContent],
        model: str | None = None,
    ) -> list[SectionContent]:
        """Humanize all sections (skips intro and conclusion)."""
        result = []
        for section in sections:
            # Skip intro (chapter 0) and conclusion (chapter 99)
            if section.chapter_number in (0, 99):
                result.append(section)
                continue

            humanized = await self.humanize_section(section, model=model)
            result.append(humanized)

        return result

    async def _cycle_through_languages(self, text: str) -> str:
        """Translate text through the language chain."""
        current = text
        for i in range(len(self._chain) - 1):
            source = self._chain[i]
            target = self._chain[i + 1]
            current = await self._translator.translate(current, source, target)
        return current
