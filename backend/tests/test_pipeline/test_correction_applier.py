"""Tests for the CorrectionApplier — targeted sentence replacement for fact-check fixes."""

from backend.app.pipeline.verifier.correction_applier import CorrectionApplier
from backend.app.testing import MockLLMProvider
from shared.schemas.pipeline import (
    ClaimVerdict,
    FactCheckClaim,
    FactCheckResult,
    SectionContent,
)


def _make_section(title: str = "1.1 Тест", content: str = "", chapter: int = 1) -> SectionContent:
    return SectionContent(
        chapter_number=chapter,
        section_title=title,
        content=content,
        word_count=len(content.split()),
    )


def _make_claim(
    text: str,
    section: str = "1.1 Тест",
    verdict: ClaimVerdict = ClaimVerdict.UNSUPPORTED,
    correction: str | None = "Исправленный факт",
) -> FactCheckClaim:
    return FactCheckClaim(
        claim_text=text,
        source_section=section,
        verdict=verdict,
        confidence=0.8,
        correction=correction,
    )


def _make_fact_check(claims: list[FactCheckClaim]) -> FactCheckResult:
    return FactCheckResult(
        total_claims=len(claims),
        checked_claims=len(claims),
        unsupported=sum(1 for c in claims if c.verdict == ClaimVerdict.UNSUPPORTED),
        claims=claims,
    )


class TestFindSentence:
    def test_exact_match(self) -> None:
        text = "Первое предложение. Второе предложение с данными 50%. Третье."
        result = CorrectionApplier._find_sentence(text, "данными 50%")
        assert result is not None
        assert "50%" in result

    def test_case_insensitive_match(self) -> None:
        text = "По данным McKinsey, рост составил 70%. Это важно."
        result = CorrectionApplier._find_sentence(text, "по данным mckinsey, рост составил 70%")
        assert result is not None
        assert "McKinsey" in result

    def test_key_token_fallback(self) -> None:
        text = "Исследование Deloitte показало рост на 56%. Другие данные."
        # Claim text is paraphrased but shares key tokens
        result = CorrectionApplier._find_sentence(text, "Deloitte обнаружил увеличение на 56%")
        assert result is not None
        assert "Deloitte" in result

    def test_no_match_returns_none(self) -> None:
        text = "Простой текст без совпадений. Ещё предложение."
        result = CorrectionApplier._find_sentence(text, "совершенно другое утверждение 99%")
        assert result is None

    def test_single_sentence_text(self) -> None:
        text = "Единственное предложение с числом 42."
        result = CorrectionApplier._find_sentence(text, "числом 42")
        assert result is not None


class TestFindSection:
    def test_exact_title_match(self) -> None:
        sections = [
            _make_section("Введение", "текст введения"),
            _make_section("1.1 Теория", "текст теории"),
        ]
        claim = _make_claim("факт", section="1.1 Теория")
        result = CorrectionApplier._find_section(sections, claim)
        assert result is not None
        assert result.section_title == "1.1 Теория"

    def test_fallback_to_content_search(self) -> None:
        sections = [
            _make_section("Раздел А", "обычный текст без фактов"),
            _make_section("Раздел Б", "текст с упоминанием роста на 70%"),
        ]
        claim = _make_claim("роста на 70%", section="Несуществующий раздел")
        result = CorrectionApplier._find_section(sections, claim)
        assert result is not None
        assert result.section_title == "Раздел Б"

    def test_not_found(self) -> None:
        sections = [_make_section("Раздел", "простой текст")]
        claim = _make_claim("совсем другой факт", section="Другой раздел")
        result = CorrectionApplier._find_section(sections, claim)
        assert result is None


class TestGetContext:
    def test_context_with_surrounding_sentences(self) -> None:
        text = "Первое. Второе. Третье. Четвёртое."
        context = CorrectionApplier._get_context(text, "Второе.", window=1)
        assert "Первое." in context
        assert ">>> Второе. <<<" in context
        assert "Третье." in context

    def test_context_at_start(self) -> None:
        text = "Первое. Второе. Третье."
        context = CorrectionApplier._get_context(text, "Первое.", window=1)
        assert ">>> Первое. <<<" in context

    def test_sentence_not_found(self) -> None:
        text = "Первое. Второе."
        context = CorrectionApplier._get_context(text, "Отсутствует.", window=1)
        assert context == ""


class TestApplyCorrections:
    async def test_applies_correction_to_matching_sentence(
        self, mock_llm: MockLLMProvider,
    ) -> None:
        original_text = (
            "По данным McKinsey, 70% компаний внедряют цифровые технологии. "
            "Это подтверждается другими исследованиями."
        )
        corrected_sentence = (
            "По данным McKinsey, 65% компаний внедряют цифровые технологии."
        )

        mock_llm.set_responses([corrected_sentence])

        sections = [_make_section("1.1 Обзор", original_text)]
        claims = [_make_claim(
            "70% компаний внедряют цифровые технологии",
            section="1.1 Обзор",
            correction="По данным McKinsey (2024), показатель составляет 65%",
        )]
        fact_check = _make_fact_check(claims)

        applier = CorrectionApplier(mock_llm)
        updated_sections, applied = await applier.apply_corrections(
            sections=sections,
            fact_check=fact_check,
            model="test-model",
        )

        assert applied == 1
        assert "65%" in updated_sections[0].content
        assert "70%" not in updated_sections[0].content

    async def test_skips_claims_without_correction(
        self, mock_llm: MockLLMProvider,
    ) -> None:
        sections = [_make_section("1.1 Обзор", "Текст секции.")]
        claims = [_make_claim("факт", correction=None)]
        fact_check = _make_fact_check(claims)

        applier = CorrectionApplier(mock_llm)
        _, applied = await applier.apply_corrections(
            sections=sections, fact_check=fact_check,
        )
        assert applied == 0
        assert len(mock_llm.calls) == 0

    async def test_skips_claims_with_empty_correction(
        self, mock_llm: MockLLMProvider,
    ) -> None:
        sections = [_make_section("1.1 Обзор", "Текст секции.")]
        claims = [_make_claim("факт", correction="   ")]
        fact_check = _make_fact_check(claims)

        applier = CorrectionApplier(mock_llm)
        _, applied = await applier.apply_corrections(
            sections=sections, fact_check=fact_check,
        )
        assert applied == 0

    async def test_skips_when_section_not_found(
        self, mock_llm: MockLLMProvider,
    ) -> None:
        sections = [_make_section("Раздел А", "Обычный текст")]
        claims = [_make_claim(
            "несуществующий факт",
            section="Раздел Б",
            correction="Исправление",
        )]
        fact_check = _make_fact_check(claims)

        applier = CorrectionApplier(mock_llm)
        _, applied = await applier.apply_corrections(
            sections=sections, fact_check=fact_check,
        )
        assert applied == 0

    async def test_skips_when_sentence_not_found(
        self, mock_llm: MockLLMProvider,
    ) -> None:
        sections = [_make_section("1.1 Обзор", "Простой текст без совпадений.")]
        claims = [_make_claim(
            "совершенно другое утверждение с числом 999",
            section="1.1 Обзор",
            correction="Исправление",
        )]
        fact_check = _make_fact_check(claims)

        applier = CorrectionApplier(mock_llm)
        _, applied = await applier.apply_corrections(
            sections=sections, fact_check=fact_check,
        )
        assert applied == 0

    async def test_rejects_correction_with_bad_length(
        self, mock_llm: MockLLMProvider,
    ) -> None:
        sections = [_make_section("1.1 Обзор", "Факт: рост 70% в 2024 году. Второе.")]
        claims = [_make_claim("рост 70%", section="1.1 Обзор")]

        # LLM returns way too short response
        mock_llm.set_responses(["Да."])

        applier = CorrectionApplier(mock_llm)
        _, applied = await applier.apply_corrections(
            sections=sections, fact_check=_make_fact_check(claims),
        )
        assert applied == 0

    async def test_multiple_corrections(
        self, mock_llm: MockLLMProvider,
    ) -> None:
        text = (
            "По данным исследования, рост составил 80%. "
            "Компания Apple основана в 1975 году. "
            "Другие данные подтверждают тренд."
        )
        sections = [_make_section("1.1 Обзор", text)]
        claims = [
            _make_claim(
                "рост составил 80%",
                section="1.1 Обзор",
                correction="Рост составил 65%",
            ),
            _make_claim(
                "Apple основана в 1975 году",
                section="1.1 Обзор",
                correction="Apple основана в 1976 году",
            ),
        ]

        mock_llm.set_responses([
            "По данным исследования, рост составил 65%.",
            "Компания Apple основана в 1976 году.",
        ])

        applier = CorrectionApplier(mock_llm)
        updated, applied = await applier.apply_corrections(
            sections=sections, fact_check=_make_fact_check(claims),
        )

        assert applied == 2
        assert "65%" in updated[0].content
        assert "1976" in updated[0].content
        assert "80%" not in updated[0].content
        assert "1975" not in updated[0].content

    async def test_word_count_updated_after_correction(
        self, mock_llm: MockLLMProvider,
    ) -> None:
        text = "Факт: рост 70% за год. Второе предложение."
        sections = [_make_section("1.1 Обзор", text)]
        claims = [_make_claim("рост 70%", section="1.1 Обзор")]

        mock_llm.set_responses([
            "Факт: рост составил примерно 65% за прошедший год."
        ])

        applier = CorrectionApplier(mock_llm)
        updated, applied = await applier.apply_corrections(
            sections=sections, fact_check=_make_fact_check(claims),
        )

        assert applied == 1
        assert updated[0].word_count == len(updated[0].content.split())

    async def test_no_claims_returns_unchanged(
        self, mock_llm: MockLLMProvider,
    ) -> None:
        sections = [_make_section("1.1 Обзор", "Текст.")]
        fact_check = _make_fact_check([])

        applier = CorrectionApplier(mock_llm)
        updated, applied = await applier.apply_corrections(
            sections=sections, fact_check=fact_check,
        )

        assert applied == 0
        assert updated[0].content == "Текст."
