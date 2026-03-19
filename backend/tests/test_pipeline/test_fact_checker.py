"""Tests for the fact verification pipeline."""

import json

import pytest

from backend.app.pipeline.verifier.claim_extractor import ClaimExtractor
from backend.app.pipeline.verifier.fact_checker import FactChecker
from backend.app.pipeline.verifier.stage import VerifierStage
from backend.app.testing import MockLLMProvider, MockSearchProvider
from shared.schemas.pipeline import (
    ClaimVerdict,
    FactCheckClaim,
    PipelineConfig,
    SectionContent,
    Source,
)


@pytest.fixture
def claim_extractor(mock_llm: MockLLMProvider) -> ClaimExtractor:
    return ClaimExtractor(mock_llm)


@pytest.fixture
def fact_checker(
    mock_llm: MockLLMProvider, mock_search: MockSearchProvider
) -> FactChecker:
    return FactChecker(mock_llm, mock_search)


class TestClaimExtractor:
    async def test_extract_claims(
        self,
        claim_extractor: ClaimExtractor,
        mock_llm: MockLLMProvider,
    ) -> None:
        mock_llm.set_responses([
            json.dumps({
                "claims": [
                    {
                        "claim_text": "70% компаний внедряют цифровые технологии",
                        "source_section": "Глава 1",
                    },
                    {
                        "claim_text": "Расходы на ИТ выросли на 15% в 2024 году",
                        "source_section": "Глава 1",
                    },
                ]
            })
        ])

        claims = await claim_extractor.extract(
            text="Согласно McKinsey, 70% компаний внедряют цифровые технологии." * 10,
            section_title="Глава 1",
            max_claims=5,
        )

        assert len(claims) == 2
        assert "70%" in claims[0].claim_text

    async def test_skip_short_text(self, claim_extractor: ClaimExtractor) -> None:
        claims = await claim_extractor.extract(
            text="Короткий текст",
            section_title="Test",
        )
        assert len(claims) == 0

    async def test_handles_invalid_json(
        self,
        claim_extractor: ClaimExtractor,
        mock_llm: MockLLMProvider,
    ) -> None:
        mock_llm.set_responses(["invalid"])

        claims = await claim_extractor.extract(
            text="x " * 60,
            section_title="Test",
        )
        assert len(claims) == 0


class TestFactChecker:
    async def test_supported_verdict(
        self,
        fact_checker: FactChecker,
        mock_llm: MockLLMProvider,
        mock_search: MockSearchProvider,
    ) -> None:
        mock_search.set_results([
            Source(
                url="https://source.com",
                title="Confirming source",
                snippet="Indeed, 70% of companies...",
            )
        ])
        mock_llm.set_responses([
            "VERDICT: supported\n"
            "CONFIDENCE: 0.9\n"
            "EVIDENCE: Multiple sources confirm this statistic.\n"
            "CORRECTION: нет"
        ])

        claim = FactCheckClaim(
            claim_text="70% companies adopt digital tech",
            source_section="Ch1",
        )

        result = await fact_checker.check_claim(claim)

        assert result.verdict == ClaimVerdict.SUPPORTED
        assert result.confidence == 0.9
        assert result.correction is None

    async def test_unsupported_verdict_with_correction(
        self,
        fact_checker: FactChecker,
        mock_llm: MockLLMProvider,
        mock_search: MockSearchProvider,
    ) -> None:
        mock_search.set_results([
            Source(url="https://a.com", title="Counter", snippet="Actually only 40%..."),
        ])
        mock_llm.set_responses([
            "VERDICT: unsupported\n"
            "CONFIDENCE: 0.8\n"
            "EVIDENCE: Sources indicate the real figure is 40%.\n"
            "CORRECTION: Доля компаний составляет 40%, а не 70%."
        ])

        claim = FactCheckClaim(claim_text="70% stat", source_section="Ch1")
        result = await fact_checker.check_claim(claim)

        assert result.verdict == ClaimVerdict.UNSUPPORTED
        assert result.correction is not None
        assert "40%" in result.correction

    async def test_no_search_results(
        self,
        fact_checker: FactChecker,
        mock_search: MockSearchProvider,
    ) -> None:
        mock_search.set_results([])

        claim = FactCheckClaim(claim_text="Unverifiable claim", source_section="Ch1")
        result = await fact_checker.check_claim(claim, max_rounds=2)

        assert result.verdict == ClaimVerdict.UNCERTAIN
        assert result.confidence == 0.0
        assert len(mock_search.queries) == 1

    async def test_iterative_check_reformulates_on_uncertainty(
        self,
        fact_checker: FactChecker,
        mock_llm: MockLLMProvider,
        mock_search: MockSearchProvider,
    ) -> None:
        """Test that uncertain results trigger a query reformulation and second search."""
        mock_search.set_results([
            Source(url="https://s.com", title="Vague", snippet="Some vague info"),
        ])

        # Round 1: uncertain, low confidence → reformulate
        # Round 2: reformulated query → supported
        mock_llm.set_responses([
            # Round 1 verdict
            "VERDICT: uncertain\n"
            "CONFIDENCE: 0.3\n"
            "EVIDENCE: Not enough data.\n"
            "CORRECTION: нет",
            # Reformulation
            "цифровизация бизнеса статистика Россия 2024",
            # Round 2 verdict
            "VERDICT: supported\n"
            "CONFIDENCE: 0.85\n"
            "EVIDENCE: Confirmed by multiple sources.\n"
            "CORRECTION: нет",
        ])

        claim = FactCheckClaim(claim_text="70% companies digitize", source_section="Ch1")
        result = await fact_checker.check_claim(claim, max_rounds=2)

        assert result.verdict == ClaimVerdict.SUPPORTED
        assert result.confidence == 0.85
        # Should have searched twice
        assert len(mock_search.queries) == 2

    async def test_iterative_check_stops_on_confident_result(
        self,
        fact_checker: FactChecker,
        mock_llm: MockLLMProvider,
        mock_search: MockSearchProvider,
    ) -> None:
        """High-confidence result in round 1 should stop without reformulation."""
        mock_search.set_results([
            Source(url="https://s.com", title="Clear source", snippet="Definitively confirmed"),
        ])
        mock_llm.set_responses([
            "VERDICT: supported\n"
            "CONFIDENCE: 0.95\n"
            "EVIDENCE: Strongly confirmed.\n"
            "CORRECTION: нет",
        ])

        claim = FactCheckClaim(claim_text="Clear fact", source_section="Ch1")
        result = await fact_checker.check_claim(claim, max_rounds=3)

        assert result.verdict == ClaimVerdict.SUPPORTED
        # Only one search, no reformulation
        assert len(mock_search.queries) == 1
        assert len(mock_llm.calls) == 1

    async def test_iterative_check_no_results_all_rounds(
        self,
        fact_checker: FactChecker,
        mock_llm: MockLLMProvider,
        mock_search: MockSearchProvider,
    ) -> None:
        """No search results across all rounds → stays uncertain."""
        mock_search.set_results([])

        # Only reformulation responses needed
        mock_llm.set_responses([
            "alternative search query",
        ])

        claim = FactCheckClaim(claim_text="Obscure claim", source_section="Ch1")
        result = await fact_checker.check_claim(claim, max_rounds=2)

        assert result.verdict == ClaimVerdict.UNCERTAIN
        assert result.confidence == 0.0
        assert len(mock_search.queries) == 1


class TestVerifierStage:
    async def test_skips_intro_and_conclusion(
        self,
        mock_llm: MockLLMProvider,
        mock_search: MockSearchProvider,
    ) -> None:
        verifier = VerifierStage(mock_llm, mock_search)

        mock_llm.set_responses([
            json.dumps({"claims": []}),
        ])

        sections = [
            SectionContent(chapter_number=0, section_title="Введение", content="x " * 60),
            SectionContent(chapter_number=1, section_title="Глава 1", content="x " * 60),
            SectionContent(chapter_number=99, section_title="Заключение", content="x " * 60),
        ]

        _result = await verifier.run(sections)

        # Only chapter 1 should be checked
        assert len(mock_llm.calls) == 1

    async def test_disabled_fact_check(
        self,
        mock_llm: MockLLMProvider,
        mock_search: MockSearchProvider,
    ) -> None:
        verifier = VerifierStage(mock_llm, mock_search)
        config = PipelineConfig(enable_fact_check=False)

        result = await verifier.run([], config=config)

        assert result.total_claims == 0
        assert len(mock_llm.calls) == 0
