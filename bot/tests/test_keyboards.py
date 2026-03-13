"""Tests for Telegram bot keyboard layouts."""

from bot.app.keyboards.inline import (
    get_confirm_keyboard,
    get_page_count_keyboard,
    get_work_type_keyboard,
)
from shared.schemas.job import WorkType


class TestWorkTypeKeyboard:
    def test_work_type_keyboard_has_two_buttons(self) -> None:
        kb = get_work_type_keyboard()
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        assert len(buttons) == 2
        callback_data = {btn.callback_data for btn in buttons}
        assert "worktype:coursework" in callback_data
        assert "worktype:article" in callback_data


class TestPageCountKeyboard:
    def test_has_correct_options(self) -> None:
        kb = get_page_count_keyboard()
        # Flatten all buttons
        all_buttons = [btn for row in kb.inline_keyboard for btn in row]
        callback_data = [btn.callback_data for btn in all_buttons]

        assert "pages:20" in callback_data
        assert "pages:25" in callback_data
        assert "pages:30" in callback_data
        assert "pages:35" in callback_data
        assert "pages:40" in callback_data
        assert "pages:50" in callback_data

    def test_layout_has_two_rows(self) -> None:
        kb = get_page_count_keyboard()
        assert len(kb.inline_keyboard) == 2
        assert len(kb.inline_keyboard[0]) == 3
        assert len(kb.inline_keyboard[1]) == 3

    def test_page_count_keyboard_article_pages(self) -> None:
        kb = get_page_count_keyboard(WorkType.ARTICLE)
        page_counts = {
            int(btn.callback_data.split(":")[1])
            for row in kb.inline_keyboard
            for btn in row
        }
        assert page_counts == {5, 8, 10, 12, 15, 20}

    def test_page_count_keyboard_coursework_pages(self) -> None:
        kb = get_page_count_keyboard(WorkType.COURSEWORK)
        page_counts = {
            int(btn.callback_data.split(":")[1])
            for row in kb.inline_keyboard
            for btn in row
        }
        assert page_counts == {20, 25, 30, 35, 40, 50}


class TestConfirmKeyboard:
    def test_has_yes_and_no(self) -> None:
        kb = get_confirm_keyboard()
        all_buttons = [btn for row in kb.inline_keyboard for btn in row]
        callback_data = [btn.callback_data for btn in all_buttons]

        assert "confirm:yes" in callback_data
        assert "confirm:no" in callback_data

    def test_has_one_row(self) -> None:
        kb = get_confirm_keyboard()
        assert len(kb.inline_keyboard) == 1
