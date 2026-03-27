"""Tests for outline_parser — direct parsing of user-provided outline text."""

from backend.app.pipeline.writer.outline_parser import parse_outline_text


class TestParseOutlineText:
    def test_basic_chapters_and_subsections(self) -> None:
        text = (
            "Глава 1. Теоретические основы\n"
            "1.1. Понятие цифровизации\n"
            "1.2. Обзор литературы\n"
            "Глава 2. Практическая часть\n"
            "2.1. Методология\n"
            "2.2. Результаты\n"
        )
        outline = parse_outline_text(text, topic="Тест", page_count=30)
        assert outline is not None
        assert len(outline.chapters) == 2
        assert outline.chapters[0].title == "Теоретические основы"
        assert outline.chapters[0].number == 1
        assert len(outline.chapters[0].subsections) == 2
        assert "Понятие цифровизации" in outline.chapters[0].subsections[0]
        assert outline.chapters[1].title == "Практическая часть"
        assert len(outline.chapters[1].subsections) == 2

    def test_chapters_without_glava_prefix(self) -> None:
        text = (
            "1. Теоретические основы\n"
            "1.1. Понятие\n"
            "2. Анализ\n"
            "2.1. Методы\n"
        )
        outline = parse_outline_text(text, topic="Тест")
        assert outline is not None
        assert len(outline.chapters) == 2
        assert outline.chapters[0].title == "Теоретические основы"

    def test_skip_introduction_and_conclusion(self) -> None:
        text = (
            "Введение\n"
            "Глава 1. Теория\n"
            "1.1. Основы\n"
            "Заключение\n"
            "Список использованных источников\n"
        )
        outline = parse_outline_text(text)
        assert outline is not None
        assert len(outline.chapters) == 1
        assert outline.chapters[0].title == "Теория"

    def test_skip_bibliography_variations(self) -> None:
        text = (
            "Глава 1. Теория\n"
            "1.1. Основы\n"
            "Библиографический список\n"
            "Список литературы\n"
        )
        outline = parse_outline_text(text)
        assert outline is not None
        assert len(outline.chapters) == 1

    def test_returns_none_for_empty_text(self) -> None:
        assert parse_outline_text("") is None
        assert parse_outline_text("   \n  \n  ") is None

    def test_returns_none_for_unrecognizable_text(self) -> None:
        text = "Просто текст без структуры\nЕще одна строка\nИ третья"
        assert parse_outline_text(text) is None

    def test_chapter_without_subsections(self) -> None:
        text = (
            "Глава 1. Обзор литературы\n"
            "Глава 2. Практический анализ\n"
        )
        outline = parse_outline_text(text)
        assert outline is not None
        assert len(outline.chapters) == 2
        assert outline.chapters[0].subsections == []
        assert outline.chapters[1].subsections == []

    def test_subsections_before_chapter_header(self) -> None:
        """If subsections appear without a chapter header, a synthetic chapter is created."""
        text = (
            "1.1. Понятие\n"
            "1.2. Виды\n"
            "2.1. Анализ\n"
        )
        outline = parse_outline_text(text)
        assert outline is not None
        assert len(outline.chapters) == 2
        assert outline.chapters[0].subsections[0] == "1.1 Понятие"
        assert outline.chapters[1].subsections[0] == "2.1 Анализ"

    def test_renumbering_non_sequential_chapters(self) -> None:
        text = (
            "Глава 2. Анализ\n"
            "2.1. Методы\n"
            "Глава 5. Выводы\n"
            "5.1. Итоги\n"
        )
        outline = parse_outline_text(text)
        assert outline is not None
        assert outline.chapters[0].number == 1
        assert outline.chapters[1].number == 2
        # Subsections should be renumbered too
        assert outline.chapters[1].subsections[0].startswith("2.")

    def test_colon_separator(self) -> None:
        text = (
            "Глава 1: Теоретические основы\n"
            "1.1: Понятие\n"
        )
        outline = parse_outline_text(text)
        assert outline is not None
        assert outline.chapters[0].title == "Теоретические основы"
        assert len(outline.chapters[0].subsections) == 1

    def test_real_world_outline(self) -> None:
        """Test with a realistic coursework outline."""
        text = (
            "Введение\n"
            "Глава 1. Понятие валюты по российскому законодательству\n"
            "1.1. Экономическая и правовая сущность валюты\n"
            "1.2. Виды валюты в российском законодательстве\n"
            "1.3. Валютные ценности: понятие и классификация\n"
            "Глава 2. Правовое регулирование валютных операций\n"
            "2.1. Валютное законодательство РФ: система и структура\n"
            "2.2. Субъекты валютных правоотношений\n"
            "2.3. Виды валютных операций и порядок их осуществления\n"
            "Глава 3. Валютный контроль в Российской Федерации\n"
            "3.1. Органы и агенты валютного контроля\n"
            "3.2. Ответственность за нарушение валютного законодательства\n"
            "Заключение\n"
            "Список использованных источников\n"
        )
        outline = parse_outline_text(text, topic="Валюта и валютные ценности", page_count=35)
        assert outline is not None
        assert outline.title == "Валюта и валютные ценности"
        assert len(outline.chapters) == 3
        assert len(outline.chapters[0].subsections) == 3
        assert len(outline.chapters[1].subsections) == 3
        assert len(outline.chapters[2].subsections) == 2
        assert "Экономическая" in outline.chapters[0].subsections[0]

    def test_estimated_pages_set(self) -> None:
        text = (
            "Глава 1. Теория\n"
            "1.1. Основы\n"
            "Глава 2. Практика\n"
            "2.1. Метод\n"
        )
        outline = parse_outline_text(text, page_count=30)
        assert outline is not None
        for ch in outline.chapters:
            assert ch.estimated_pages > 0

    def test_default_title_when_topic_empty(self) -> None:
        text = "Глава 1. Теория\n1.1. Основы\n"
        outline = parse_outline_text(text, topic="")
        assert outline is not None
        assert outline.title == "Курсовая работа"

    def test_whitespace_handling(self) -> None:
        text = (
            "  Глава 1.  Теория с пробелами  \n"
            "  1.1.  Основные понятия  \n"
            "\n"
            "  Глава 2. Практика\n"
        )
        outline = parse_outline_text(text)
        assert outline is not None
        assert outline.chapters[0].title == "Теория с пробелами"
        assert len(outline.chapters) == 2
