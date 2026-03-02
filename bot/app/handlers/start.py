"""Start and help command handlers."""

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

router = Router()

WELCOME_MESSAGE = """Привет! Я CourseForge — бот для генерации курсовых работ.

Что я умею:
- Глубокий анализ темы с поиском источников
- Написание академического текста
- Проверка фактов
- Форматирование по ГОСТ 7.32-2017

Как использовать:
1. Отправь /generate — начать генерацию
2. Укажи тему, дисциплину и количество страниц
3. Дождись результата (5-15 минут)

Команды:
/generate — создать курсовую работу
/status — проверить статус текущей работы
/help — показать эту справку"""


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Handle /start command."""
    await message.answer(WELCOME_MESSAGE)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Handle /help command."""
    await message.answer(WELCOME_MESSAGE)
