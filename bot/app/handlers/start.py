"""Start and help command handlers."""

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

router = Router()

WELCOME_MESSAGE = """Привет! Я CourseForge — бот для генерации академических работ.

Что я умею:
- Генерация курсовых работ (20–50 страниц)
- Генерация научных статей (5–20 страниц)
- Глубокий анализ темы с поиском источников
- Написание академического текста
- Проверка фактов
- Форматирование по ГОСТ 7.32-2017

Как использовать:
1. Отправь /generate — выбери тип работы и начни генерацию
2. Укажи тему, дисциплину и количество страниц
3. Дождись результата (5-15 минут)

Команды:
/generate — создать курсовую работу или научную статью
/status — проверить статус текущей работы
/buy — купить кредиты
/balance — проверить баланс
/offer — публичная оферта
/help — показать эту справку

Новым пользователям — 1 бесплатный кредит!"""


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Handle /start command."""
    await message.answer(WELCOME_MESSAGE)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Handle /help command."""
    await message.answer(WELCOME_MESSAGE)
