"""Inline keyboard layouts for the Telegram bot."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def get_page_count_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for selecting target page count."""
    buttons = [
        [
            InlineKeyboardButton(text="20 стр.", callback_data="pages:20"),
            InlineKeyboardButton(text="25 стр.", callback_data="pages:25"),
            InlineKeyboardButton(text="30 стр.", callback_data="pages:30"),
        ],
        [
            InlineKeyboardButton(text="35 стр.", callback_data="pages:35"),
            InlineKeyboardButton(text="40 стр.", callback_data="pages:40"),
            InlineKeyboardButton(text="50 стр.", callback_data="pages:50"),
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
