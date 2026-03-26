"""Inline keyboard layouts for the Telegram bot."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from shared.schemas.job import WorkType

_COURSEWORK_PAGE_COUNTS = [20, 25, 30, 35, 40, 50]
_ARTICLE_PAGE_COUNTS = [5, 8, 10, 12, 15, 20]

_COURSEWORK_SOURCE_COUNTS = [10, 15, 20, 25, 30, 40]
_ARTICLE_SOURCE_COUNTS = [5, 10, 15, 20]


def get_work_type_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for selecting the type of academic work."""
    buttons = [
        [
            InlineKeyboardButton(text="📝 Курсовая работа", callback_data="worktype:coursework"),
            InlineKeyboardButton(text="📰 Научная статья", callback_data="worktype:article"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_page_count_keyboard(work_type: WorkType = WorkType.COURSEWORK) -> InlineKeyboardMarkup:
    """Keyboard for selecting target page count.

    Page ranges differ by work type:
    - Coursework: 20–50 pages
    - Article: 5–20 pages
    """
    counts = _ARTICLE_PAGE_COUNTS if work_type == WorkType.ARTICLE else _COURSEWORK_PAGE_COUNTS
    row1 = [InlineKeyboardButton(text=f"{n} стр.", callback_data=f"pages:{n}") for n in counts[:3]]
    row2 = [InlineKeyboardButton(text=f"{n} стр.", callback_data=f"pages:{n}") for n in counts[3:]]
    return InlineKeyboardMarkup(inline_keyboard=[row1, row2])


def get_source_count_keyboard(work_type: WorkType = WorkType.COURSEWORK) -> InlineKeyboardMarkup:
    """Keyboard for selecting target source count."""
    counts = _ARTICLE_SOURCE_COUNTS if work_type == WorkType.ARTICLE else _COURSEWORK_SOURCE_COUNTS
    row1 = [InlineKeyboardButton(text=f"{n} ист.", callback_data=f"sources:{n}") for n in counts[:3]]
    row2 = [InlineKeyboardButton(text=f"{n} ист.", callback_data=f"sources:{n}") for n in counts[3:]]
    rows = [row1]
    if row2:
        rows.append(row2)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_plan_question_keyboard() -> InlineKeyboardMarkup:
    """Keyboard asking if the user has a custom outline/plan."""
    buttons = [
        [
            InlineKeyboardButton(text="Да, есть план", callback_data="hasplan:yes"),
            InlineKeyboardButton(text="Нет, сгенерировать", callback_data="hasplan:no"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_confirm_keyboard() -> InlineKeyboardMarkup:
    """Confirmation keyboard (Yes/No)."""
    buttons = [
        [
            InlineKeyboardButton(text="Подтвердить", callback_data="confirm:yes"),
            InlineKeyboardButton(text="Отменить", callback_data="confirm:no"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
