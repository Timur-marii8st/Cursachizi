"""Tests for ArticleSectionWriter."""

from unittest.mock import AsyncMock

from backend.app.pipeline.writer.article_section_writer import ArticleSectionWriter
from shared.schemas.pipeline import Outline, OutlineChapter, SectionContent, Source


class MockLLMProvider:
    def __init__(self, response_content: str):
        self.generate = AsyncMock()
        mock_response = type("Response", (), {"content": response_content})()
        self.generate.return_value = mock_response


def _make_outline(**overrides) -> Outline:
    defaults = dict(
        title="Искусственный интеллект в образовании",
        introduction_points=["Актуальность темы", "Цель исследования"],
        chapters=[
            OutlineChapter(
                number=1,
                title="Теоретические основы ИИ",
                subsections=["Определения", "Классификация"],
                description="Обзор основных понятий",
                estimated_pages=3,
            ),
            OutlineChapter(
                number=2,
                title="Применение ИИ в образовательных технологиях",
                subsections=["Адаптивное обучение"],
                description="Практические примеры",
                estimated_pages=4,
            ),
        ],
        conclusion_points=["Основные результаты", "Перспективы развития"],
        keywords=["ИИ", "образование", "адаптивное обучение"],
        abstract_points=["Цель работы", "Методы", "Результаты"],
    )
    defaults.update(overrides)
    return Outline(**defaults)


def _make_sources(count: int = 3) -> list[Source]:
    return [
        Source(
            url=f"https://example.com/source{i}",
            title=f"Источник {i}: Исследование ИИ",
            snippet=f"Краткое описание источника {i}.",
            full_text=f"Полный текст источника {i} о применении искусственного интеллекта.",
            relevance_score=0.9 - i * 0.1,
            is_academic=True,
            language="ru",
        )
        for i in range(1, count + 1)
    ]


# ── write_abstract ──────────────────────────────────────────────────


async def test_write_abstract_returns_section_content():
    llm = MockLLMProvider("Аннотация к научной статье об ИИ в образовании.")
    writer = ArticleSectionWriter(llm)
    outline = _make_outline()

    result = await writer.write_abstract(topic="ИИ в образовании", outline=outline)

    assert isinstance(result, SectionContent)
    assert result.chapter_number == -1
    assert result.section_title == "Аннотация"
    assert result.content == "Аннотация к научной статье об ИИ в образовании."
    assert result.word_count == len(result.content.split())


async def test_write_abstract_passes_model_to_llm():
    llm = MockLLMProvider("Текст аннотации.")
    writer = ArticleSectionWriter(llm)
    outline = _make_outline()

    await writer.write_abstract(topic="Тема", outline=outline, model="gpt-4o")

    call_kwargs = llm.generate.call_args
    assert call_kwargs.kwargs["model"] == "gpt-4o"


async def test_write_abstract_with_empty_abstract_points():
    llm = MockLLMProvider("Аннотация без пунктов.")
    writer = ArticleSectionWriter(llm)
    outline = _make_outline(abstract_points=[])

    result = await writer.write_abstract(topic="Тема", outline=outline)

    assert result.chapter_number == -1
    assert result.content == "Аннотация без пунктов."


async def test_write_abstract_strips_whitespace():
    llm = MockLLMProvider("  Аннотация с пробелами.  \n")
    writer = ArticleSectionWriter(llm)
    outline = _make_outline()

    result = await writer.write_abstract(topic="Тема", outline=outline)

    assert result.content == "Аннотация с пробелами."


# ── write_introduction ──────────────────────────────────────────────


async def test_write_introduction_returns_section_content():
    llm = MockLLMProvider("Введение к статье об ИИ в образовании.")
    writer = ArticleSectionWriter(llm)
    outline = _make_outline()

    result = await writer.write_introduction(
        topic="ИИ в образовании",
        discipline="Информатика",
        outline=outline,
        target_words=500,
    )

    assert isinstance(result, SectionContent)
    assert result.chapter_number == 0
    assert result.section_title == "Введение"
    assert result.content == "Введение к статье об ИИ в образовании."
    assert result.word_count == len(result.content.split())


async def test_write_introduction_uses_default_target_words():
    llm = MockLLMProvider("Введение.")
    writer = ArticleSectionWriter(llm)
    outline = _make_outline()

    await writer.write_introduction(
        topic="Тема", discipline="Математика", outline=outline
    )

    call_kwargs = llm.generate.call_args
    prompt_content = call_kwargs.kwargs["messages"][0].content
    assert "500" in prompt_content


async def test_write_introduction_with_empty_discipline():
    llm = MockLLMProvider("Введение без дисциплины.")
    writer = ArticleSectionWriter(llm)
    outline = _make_outline()

    result = await writer.write_introduction(
        topic="Тема", discipline="", outline=outline
    )

    call_kwargs = llm.generate.call_args
    prompt_content = call_kwargs.kwargs["messages"][0].content
    assert "не указана" in prompt_content
    assert result.chapter_number == 0


# ── write_section ───────────────────────────────────────────────────


async def test_write_section_returns_section_content():
    content_with_refs = (
        "Исследование показало [1] важность ИИ. "
        "По данным [2], эффективность повышается. "
        "Также отмечается [3] рост интереса."
    )
    llm = MockLLMProvider(content_with_refs)
    writer = ArticleSectionWriter(llm)
    chapter = OutlineChapter(
        number=1,
        title="Теоретические основы",
        subsections=["Определения"],
        description="Обзор",
        estimated_pages=3,
    )
    sources = _make_sources(3)

    result = await writer.write_section(
        paper_title="ИИ в образовании",
        chapter=chapter,
        sources=sources,
        previous_sections=[],
        target_words=600,
    )

    assert isinstance(result, SectionContent)
    assert result.chapter_number == 1
    assert result.section_title == "Теоретические основы"
    assert result.word_count == len(result.content.split())


async def test_write_section_extracts_citations():
    content_with_refs = "Текст [1] и ещё [3] ссылка, а также [1] повтор."
    llm = MockLLMProvider(content_with_refs)
    writer = ArticleSectionWriter(llm)
    chapter = OutlineChapter(
        number=2,
        title="Раздел",
        subsections=[],
        description="",
        estimated_pages=2,
    )

    result = await writer.write_section(
        paper_title="Статья",
        chapter=chapter,
        sources=_make_sources(3),
        previous_sections=[],
    )

    # Citations should be unique (set), containing "1" and "3"
    assert set(result.citations) == {"1", "3"}


async def test_write_section_no_citations_in_plain_text():
    llm = MockLLMProvider("Текст без ссылок на источники.")
    writer = ArticleSectionWriter(llm)
    chapter = OutlineChapter(
        number=1, title="Раздел", subsections=[], description="", estimated_pages=2
    )

    result = await writer.write_section(
        paper_title="Статья",
        chapter=chapter,
        sources=_make_sources(1),
        previous_sections=[],
    )

    assert result.citations == []


async def test_write_section_with_previous_sections():
    llm = MockLLMProvider("Продолжение текста [1].")
    writer = ArticleSectionWriter(llm)
    chapter = OutlineChapter(
        number=2, title="Второй раздел", subsections=[], description="", estimated_pages=2
    )
    prev = SectionContent(
        chapter_number=1,
        section_title="Первый раздел",
        content="Содержимое первого раздела.",
        word_count=3,
    )

    result = await writer.write_section(
        paper_title="Статья",
        chapter=chapter,
        sources=_make_sources(2),
        previous_sections=[prev],
    )

    assert result.chapter_number == 2
    # Verify previous context was included in the prompt
    prompt_content = llm.generate.call_args.kwargs["messages"][0].content
    assert "Первый раздел" in prompt_content


async def test_write_section_with_additional_instructions():
    llm = MockLLMProvider("Текст с инструкциями [1].")
    writer = ArticleSectionWriter(llm)
    chapter = OutlineChapter(
        number=1, title="Раздел", subsections=[], description="", estimated_pages=2
    )

    await writer.write_section(
        paper_title="Статья",
        chapter=chapter,
        sources=_make_sources(1),
        previous_sections=[],
        additional_instructions="Уделить внимание методологии",
    )

    prompt_content = llm.generate.call_args.kwargs["messages"][0].content
    assert "Уделить внимание методологии" in prompt_content


async def test_write_section_empty_additional_instructions_uses_default():
    llm = MockLLMProvider("Текст [1].")
    writer = ArticleSectionWriter(llm)
    chapter = OutlineChapter(
        number=1, title="Раздел", subsections=[], description="", estimated_pages=2
    )

    await writer.write_section(
        paper_title="Статья",
        chapter=chapter,
        sources=_make_sources(1),
        previous_sections=[],
        additional_instructions="",
    )

    prompt_content = llm.generate.call_args.kwargs["messages"][0].content
    assert "Нет дополнительных инструкций" in prompt_content


# ── write_conclusion ────────────────────────────────────────────────


async def test_write_conclusion_returns_section_content():
    llm = MockLLMProvider("Заключение по результатам исследования.")
    writer = ArticleSectionWriter(llm)
    outline = _make_outline()
    sections = [
        SectionContent(
            chapter_number=1,
            section_title="Теоретические основы ИИ",
            content="Текст раздела 1.",
            word_count=3,
        ),
        SectionContent(
            chapter_number=2,
            section_title="Применение ИИ",
            content="Текст раздела 2.",
            word_count=3,
        ),
    ]

    result = await writer.write_conclusion(
        topic="ИИ в образовании",
        outline=outline,
        sections=sections,
        target_words=400,
    )

    assert isinstance(result, SectionContent)
    assert result.chapter_number == 99
    assert result.section_title == "Заключение"
    assert result.content == "Заключение по результатам исследования."
    assert result.word_count == len(result.content.split())


async def test_write_conclusion_includes_sections_summary_in_prompt():
    llm = MockLLMProvider("Заключение.")
    writer = ArticleSectionWriter(llm)
    outline = _make_outline()
    sections = [
        SectionContent(
            chapter_number=1,
            section_title="Теоретические основы ИИ",
            content="Текст.",
            word_count=10,
        ),
    ]

    await writer.write_conclusion(
        topic="Тема", outline=outline, sections=sections
    )

    prompt_content = llm.generate.call_args.kwargs["messages"][0].content
    assert "Теоретические основы ИИ" in prompt_content
    assert "10 слов" in prompt_content


async def test_write_conclusion_passes_model_to_llm():
    llm = MockLLMProvider("Заключение.")
    writer = ArticleSectionWriter(llm)
    outline = _make_outline()

    await writer.write_conclusion(
        topic="Тема", outline=outline, sections=[], model="claude-3"
    )

    assert llm.generate.call_args.kwargs["model"] == "claude-3"


async def test_write_conclusion_with_empty_sections():
    llm = MockLLMProvider("Заключение без разделов.")
    writer = ArticleSectionWriter(llm)
    outline = _make_outline()

    result = await writer.write_conclusion(
        topic="Тема", outline=outline, sections=[]
    )

    assert result.chapter_number == 99
    assert result.section_title == "Заключение"
