"""Parser for user-provided outline text into structured Outline objects.

Parses patterns like:
    Глава 1. Теоретические основы
    1.1. Понятие X
    1.2. Обзор Y
    Глава 2. Практическая часть
    2.1. Методология
"""

import re

import structlog

from shared.schemas.pipeline import Outline, OutlineChapter

logger = structlog.get_logger()

# Patterns for chapter headers:
#   "Глава 1. Title" / "ГЛАВА 1. TITLE" / "Глава 1: Title" / "Глава I. Title"
#   "1. Title" (standalone number at line start)
_CHAPTER_RE = re.compile(
    r"^\s*(?:глава\s+)?(\d+)[.:\s)]+\s*(.+)",
    re.IGNORECASE,
)

# Patterns for subsection headers:
#   "1.1. Title" / "1.1 Title" / "1.1) Title"
_SUBSECTION_RE = re.compile(
    r"^\s*(\d+)\.(\d+)[.:\s)]+\s*(.+)",
)

# Lines to skip (introduction, conclusion, bibliography markers)
_SKIP_RE = re.compile(
    r"^\s*(введение|заключение|список\s+(?:использованных\s+)?(?:источников|литературы)"
    r"|библиографический\s+список|содержание|оглавление)\s*$",
    re.IGNORECASE,
)


def parse_outline_text(text: str, topic: str = "", page_count: int = 30) -> Outline | None:
    """Parse user-provided outline text into an Outline object.

    Returns None if the text cannot be parsed (no chapters detected).
    """
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]

    chapters: list[OutlineChapter] = []
    current_chapter: dict | None = None

    for line in lines:
        # Skip intro/conclusion/bibliography markers
        if _SKIP_RE.match(line):
            continue

        # Try subsection first (more specific pattern)
        sub_match = _SUBSECTION_RE.match(line)
        if sub_match:
            chapter_num = int(sub_match.group(1))
            sub_num = sub_match.group(2)
            sub_title = sub_match.group(3).strip()

            # If no current chapter or different chapter number, create one
            if current_chapter is None or current_chapter["number"] != chapter_num:
                if current_chapter is not None:
                    chapters.append(_build_chapter(current_chapter, page_count, len(chapters)))
                current_chapter = {
                    "number": chapter_num,
                    "title": f"Глава {chapter_num}",
                    "subsections": [],
                }
            current_chapter["subsections"].append(f"{chapter_num}.{sub_num} {sub_title}")
            continue

        # Try chapter header
        ch_match = _CHAPTER_RE.match(line)
        if ch_match:
            # Save previous chapter
            if current_chapter is not None:
                chapters.append(_build_chapter(current_chapter, page_count, len(chapters)))

            chapter_num = int(ch_match.group(1))
            chapter_title = ch_match.group(2).strip()

            current_chapter = {
                "number": chapter_num,
                "title": chapter_title,
                "subsections": [],
            }
            continue

    # Save last chapter
    if current_chapter is not None:
        chapters.append(_build_chapter(current_chapter, page_count, len(chapters)))

    if not chapters:
        logger.warning("outline_parser_no_chapters_found", text_length=len(text))
        return None

    # Renumber chapters sequentially starting from 1
    for i, ch in enumerate(chapters):
        old_num = ch.number
        ch.number = i + 1
        if old_num != ch.number:
            ch.subsections = [
                re.sub(rf"^{old_num}\.", f"{ch.number}.", s)
                for s in ch.subsections
            ]

    outline = Outline(
        title=topic or "Курсовая работа",
        introduction_points=["Актуальность темы", "Цель и задачи исследования"],
        chapters=chapters,
        conclusion_points=["Основные выводы исследования"],
    )

    logger.info(
        "outline_parsed_from_user_text",
        chapters=len(chapters),
        total_subsections=sum(len(ch.subsections) for ch in chapters),
    )

    return outline


def _build_chapter(data: dict, page_count: int, chapter_index: int) -> OutlineChapter:
    """Convert parsed chapter data dict to OutlineChapter."""
    # Estimate pages roughly evenly across chapters
    total_chapters = max(chapter_index + 1, 1)
    body_pages = page_count - 4  # minus intro/conclusion/title/toc
    estimated = max(body_pages // total_chapters, 3)

    subsection_titles = [re.sub(r"^\d+(?:\.\d+)*\.?\s*", "", item).strip() for item in data["subsections"]]
    description = ""
    if subsection_titles:
        description = "Cover the subsection topics in order: " + ", ".join(subsection_titles)

    return OutlineChapter(
        number=data["number"],
        title=data["title"],
        subsections=data["subsections"],
        description=description,
        estimated_pages=estimated,
    )
