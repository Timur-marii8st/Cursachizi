"""Tests for ArticleOutliner — scientific article outline generation."""

import json

import pytest

from backend.app.pipeline.writer.article_outliner import ArticleOutliner
from backend.app.testing import MockLLMProvider
from shared.schemas.pipeline import ResearchResult, Source


@pytest.fixture
def article_outliner(mock_llm: MockLLMProvider) -> ArticleOutliner:
    return ArticleOutliner(mock_llm)


@pytest.fixture
def sample_research() -> ResearchResult:
    return ResearchResult(
        original_topic="Методы машинного обучения в медицинской диагностике",
        expanded_queries=[
            "машинное обучение медицина диагностика",
            "нейронные сети анализ медицинских изображений",
        ],
        sources=[
            Source(
                url="https://example.com/ml-medicine",
                title="Применение ML в медицине",
                snippet="Обзор методов машинного обучения для диагностики заболеваний",
                full_text=(
                    "Машинное обучение активно применяется в медицинской "
                    "диагностике. Свёрточные нейронные сети показывают точность "
                    "до 95% при анализе рентгеновских снимков."
                ),
                relevance_score=0.92,
                is_academic=True,
            ),
            Source(
                url="https://example.com/deep-learning-radiology",
                title="Глубокое обучение в радиологии",
                snippet="Анализ эффективности DL-моделей в радиологической практике",
                full_text=(
                    "Глубокое обучение революционизирует радиологическую "
                    "диагностику. Модели на основе ResNet и EfficientNet "
                    "превосходят человеческую точность в ряде задач."
                ),
                relevance_score=0.88,
                is_academic=True,
            ),
            Source(
                url="https://example.com/ai-healthcare-stats",
                title="Статистика внедрения ИИ в здравоохранении",
                snippet="По данным ВОЗ, рынок ИИ в медицине растёт на 40% ежегодно",
                full_text=(
                    "Рынок искусственного интеллекта в здравоохранении "
                    "достигнет 45 млрд долларов к 2030 году. Основные "
                    "направления: диагностика, прогнозирование, персонализация."
                ),
                relevance_score=0.75,
            ),
        ],
        key_concepts=["машинное обучение", "нейронные сети", "диагностика"],
        summary="Обзор применения методов ML в медицинской диагностике",
    )


def _valid_article_outline_json() -> str:
    """Return a valid JSON response mimicking LLM output for an article outline."""
    return json.dumps(
        {
            "title": "Методы машинного обучения в медицинской диагностике: обзор и перспективы",
            "abstract_points": [
                "Цель работы — систематизация методов ML для медицинской диагностики",
                "Рассмотрены свёрточные нейронные сети, ансамблевые методы и трансформеры",
                "Показана эффективность моделей на реальных клинических данных",
            ],
            "keywords": [
                "машинное обучение",
                "медицинская диагностика",
                "нейронные сети",
                "глубокое обучение",
                "классификация изображений",
            ],
            "introduction_points": [
                "Актуальность автоматизации медицинской диагностики",
                "Проблема: нехватка квалифицированных специалистов",
                "Цель: анализ эффективности методов ML в диагностике",
            ],
            "sections": [
                {
                    "number": 1,
                    "title": "Обзор методов машинного обучения в медицине",
                    "description": "Теоретическая база и классификация подходов ML",
                    "estimated_pages": 3,
                },
                {
                    "number": 2,
                    "title": "Применение свёрточных нейронных сетей для анализа изображений",
                    "description": "Архитектуры CNN и их результаты на медицинских датасетах",
                    "estimated_pages": 4,
                },
                {
                    "number": 3,
                    "title": "Сравнительный анализ и результаты",
                    "description": "Метрики качества, сравнение моделей, ограничения",
                    "estimated_pages": 3,
                },
            ],
            "conclusion_points": [
                "ML-методы показывают высокую точность в задачах диагностики",
                "Необходима дальнейшая валидация на крупных клинических выборках",
            ],
        },
        ensure_ascii=False,
    )


class TestArticleOutliner:
    """Tests for ArticleOutliner.generate()."""

    async def test_successful_outline_generation(
        self,
        article_outliner: ArticleOutliner,
        mock_llm: MockLLMProvider,
        sample_research: ResearchResult,
    ) -> None:
        """LLM returns valid JSON; outline should be parsed correctly."""
        mock_llm.set_responses([_valid_article_outline_json()])

        outline = await article_outliner.generate(
            topic="Методы машинного обучения в медицинской диагностике",
            discipline="Информатика",
            page_count=10,
            research=sample_research,
        )

        assert "машинного обучения" in outline.title.lower()
        assert len(outline.chapters) == 3
        assert outline.chapters[0].number == 1
        assert outline.chapters[1].number == 2
        assert outline.chapters[2].number == 3
        assert len(outline.introduction_points) == 3
        assert len(outline.conclusion_points) == 2
        # LLM was called once
        assert len(mock_llm.calls) == 1

    async def test_outline_has_flat_structure(
        self,
        article_outliner: ArticleOutliner,
        mock_llm: MockLLMProvider,
        sample_research: ResearchResult,
    ) -> None:
        """Article sections must have empty subsections (flat structure)."""
        mock_llm.set_responses([_valid_article_outline_json()])

        outline = await article_outliner.generate(
            topic="Методы машинного обучения в медицинской диагностике",
            discipline="Информатика",
            page_count=10,
            research=sample_research,
        )

        for chapter in outline.chapters:
            assert chapter.subsections == [], (
                f"Chapter '{chapter.title}' should have no subsections in article mode"
            )

    async def test_outline_contains_keywords(
        self,
        article_outliner: ArticleOutliner,
        mock_llm: MockLLMProvider,
        sample_research: ResearchResult,
    ) -> None:
        """Outline must include article-specific keywords field."""
        mock_llm.set_responses([_valid_article_outline_json()])

        outline = await article_outliner.generate(
            topic="Методы машинного обучения в медицинской диагностике",
            discipline="Информатика",
            page_count=10,
            research=sample_research,
        )

        assert len(outline.keywords) == 5
        assert "машинное обучение" in outline.keywords
        assert "нейронные сети" in outline.keywords

    async def test_outline_contains_abstract_points(
        self,
        article_outliner: ArticleOutliner,
        mock_llm: MockLLMProvider,
        sample_research: ResearchResult,
    ) -> None:
        """Outline must include abstract_points for the article annotation."""
        mock_llm.set_responses([_valid_article_outline_json()])

        outline = await article_outliner.generate(
            topic="Методы машинного обучения в медицинской диагностике",
            discipline="Информатика",
            page_count=10,
            research=sample_research,
        )

        assert len(outline.abstract_points) == 3
        assert any("цель" in pt.lower() for pt in outline.abstract_points)

    async def test_section_descriptions_and_pages(
        self,
        article_outliner: ArticleOutliner,
        mock_llm: MockLLMProvider,
        sample_research: ResearchResult,
    ) -> None:
        """Each section should carry a description and estimated_pages."""
        mock_llm.set_responses([_valid_article_outline_json()])

        outline = await article_outliner.generate(
            topic="Методы машинного обучения в медицинской диагностике",
            discipline="Информатика",
            page_count=10,
            research=sample_research,
        )

        for chapter in outline.chapters:
            assert chapter.description, f"Chapter {chapter.number} should have a description"
            assert chapter.estimated_pages > 0

        assert outline.chapters[0].estimated_pages == 3
        assert outline.chapters[1].estimated_pages == 4

    async def test_fallback_on_invalid_json(
        self,
        article_outliner: ArticleOutliner,
        mock_llm: MockLLMProvider,
        sample_research: ResearchResult,
    ) -> None:
        """When LLM returns invalid JSON, a sensible fallback outline is produced."""
        mock_llm.set_responses(["This is not valid JSON at all!"])

        outline = await article_outliner.generate(
            topic="Тестовая тема статьи",
            discipline="Экономика",
            page_count=9,
            research=sample_research,
        )

        # Fallback uses the original topic as title
        assert outline.title == "Тестовая тема статьи"
        # Fallback has exactly 2 chapters
        assert len(outline.chapters) == 2
        assert outline.chapters[0].title == "Теоретические основы"
        assert outline.chapters[1].title == "Результаты и обсуждение"
        # Fallback chapters have empty subsections (flat structure preserved)
        for chapter in outline.chapters:
            assert chapter.subsections == []
        # Fallback populates introduction, conclusion, keywords, abstract
        assert len(outline.introduction_points) >= 1
        assert len(outline.conclusion_points) >= 1
        assert len(outline.keywords) >= 1
        assert len(outline.abstract_points) >= 1

    async def test_fallback_estimated_pages_based_on_page_count(
        self,
        article_outliner: ArticleOutliner,
        mock_llm: MockLLMProvider,
        sample_research: ResearchResult,
    ) -> None:
        """Fallback outline should divide page_count across chapters."""
        mock_llm.set_responses(["~~~broken~~~"])

        outline = await article_outliner.generate(
            topic="Тема",
            discipline="Физика",
            page_count=12,
            research=sample_research,
        )

        # page_count=12, 2 fallback chapters -> 12//3 = 4 pages each
        for chapter in outline.chapters:
            assert chapter.estimated_pages == 4

    async def test_json_in_markdown_code_block(
        self,
        article_outliner: ArticleOutliner,
        mock_llm: MockLLMProvider,
        sample_research: ResearchResult,
    ) -> None:
        """LLM sometimes wraps JSON in ```json ... ``` — outliner should handle it."""
        raw_json = _valid_article_outline_json()
        wrapped = f"```json\n{raw_json}\n```"
        mock_llm.set_responses([wrapped])

        outline = await article_outliner.generate(
            topic="Методы машинного обучения в медицинской диагностике",
            discipline="Информатика",
            page_count=10,
            research=sample_research,
        )

        assert len(outline.chapters) == 3
        assert len(outline.keywords) == 5

    async def test_model_parameter_forwarded_to_llm(
        self,
        article_outliner: ArticleOutliner,
        mock_llm: MockLLMProvider,
        sample_research: ResearchResult,
    ) -> None:
        """The model parameter should be passed through to the LLM provider."""
        mock_llm.set_responses([_valid_article_outline_json()])

        await article_outliner.generate(
            topic="Тема",
            discipline="Математика",
            page_count=8,
            research=sample_research,
            model="google/gemini-2.5-flash",
        )

        assert mock_llm.calls[0]["model"] == "google/gemini-2.5-flash"

    async def test_prompt_contains_topic_and_discipline(
        self,
        article_outliner: ArticleOutliner,
        mock_llm: MockLLMProvider,
        sample_research: ResearchResult,
    ) -> None:
        """The prompt sent to LLM should include topic, discipline, and page_count."""
        mock_llm.set_responses([_valid_article_outline_json()])

        await article_outliner.generate(
            topic="Квантовые вычисления",
            discipline="Физика",
            page_count=15,
            research=sample_research,
        )

        sent_content = mock_llm.calls[0]["messages"][0].content
        assert "Квантовые вычисления" in sent_content
        assert "Физика" in sent_content
        assert "15" in sent_content

    async def test_discipline_defaults_when_empty(
        self,
        article_outliner: ArticleOutliner,
        mock_llm: MockLLMProvider,
        sample_research: ResearchResult,
    ) -> None:
        """When discipline is empty/falsy, prompt should use the fallback text."""
        mock_llm.set_responses([_valid_article_outline_json()])

        await article_outliner.generate(
            topic="Тема",
            discipline="",
            page_count=10,
            research=sample_research,
        )

        sent_content = mock_llm.calls[0]["messages"][0].content
        assert "не указана" in sent_content

    async def test_source_summary_included_in_prompt(
        self,
        article_outliner: ArticleOutliner,
        mock_llm: MockLLMProvider,
        sample_research: ResearchResult,
    ) -> None:
        """Research source titles and snippets should appear in the prompt."""
        mock_llm.set_responses([_valid_article_outline_json()])

        await article_outliner.generate(
            topic="Тема",
            discipline="Биология",
            page_count=10,
            research=sample_research,
        )

        sent_content = mock_llm.calls[0]["messages"][0].content
        assert "Применение ML в медицине" in sent_content
        assert "Глубокое обучение в радиологии" in sent_content

    async def test_empty_sources_research(
        self,
        article_outliner: ArticleOutliner,
        mock_llm: MockLLMProvider,
    ) -> None:
        """When research has no sources, outliner should still work."""
        empty_research = ResearchResult(
            original_topic="Тема без источников",
            sources=[],
        )
        mock_llm.set_responses([_valid_article_outline_json()])

        outline = await article_outliner.generate(
            topic="Тема без источников",
            discipline="История",
            page_count=8,
            research=empty_research,
        )

        assert outline.title is not None
        assert len(outline.chapters) > 0
        # Prompt should contain the "no sources" fallback text
        sent_content = mock_llm.calls[0]["messages"][0].content
        assert "Источники не найдены" in sent_content

    async def test_missing_optional_fields_in_json(
        self,
        article_outliner: ArticleOutliner,
        mock_llm: MockLLMProvider,
        sample_research: ResearchResult,
    ) -> None:
        """JSON missing optional fields (keywords, abstract_points) should not crash."""
        minimal_json = json.dumps(
            {
                "title": "Минимальная статья",
                "sections": [
                    {"number": 1, "title": "Единственный раздел"},
                ],
            },
            ensure_ascii=False,
        )
        mock_llm.set_responses([minimal_json])

        outline = await article_outliner.generate(
            topic="Тема",
            discipline="Право",
            page_count=6,
            research=sample_research,
        )

        assert outline.title == "Минимальная статья"
        assert len(outline.chapters) == 1
        # Missing fields should default to empty lists
        assert outline.keywords == []
        assert outline.abstract_points == []
        assert outline.introduction_points == []
        assert outline.conclusion_points == []


class TestArticleOutlinerSourceSummary:
    """Tests for the _summarize_sources static method."""

    def test_summarize_with_snippets(self) -> None:
        research = ResearchResult(
            original_topic="Test",
            sources=[
                Source(url="https://a.com", title="Source A", snippet="Snippet A"),
                Source(url="https://b.com", title="Source B", snippet="Snippet B"),
            ],
        )

        summary = ArticleOutliner._summarize_sources(research)
        assert "Source A" in summary
        assert "Snippet A" in summary
        assert "Source B" in summary

    def test_summarize_falls_back_to_full_text(self) -> None:
        research = ResearchResult(
            original_topic="Test",
            sources=[
                Source(
                    url="https://c.com",
                    title="Source C",
                    snippet="",
                    full_text="Full text content for Source C that is quite detailed",
                ),
            ],
        )

        summary = ArticleOutliner._summarize_sources(research)
        assert "Source C" in summary
        assert "Full text content" in summary

    def test_summarize_empty_sources(self) -> None:
        research = ResearchResult(original_topic="Test", sources=[])
        summary = ArticleOutliner._summarize_sources(research)
        assert summary == "Источники не найдены"

    def test_summarize_limits_to_ten_sources(self) -> None:
        sources = [
            Source(url=f"https://s{i}.com", title=f"Source {i}", snippet=f"Snippet {i}")
            for i in range(15)
        ]
        research = ResearchResult(original_topic="Test", sources=sources)

        summary = ArticleOutliner._summarize_sources(research)
        assert "Source 9" in summary
        assert "Source 10" not in summary  # 0-indexed: sources[:10] -> 0..9
