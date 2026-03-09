"""Coursework generation flow handlers using FSM (Finite State Machine)."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.app.keyboards.inline import (
    get_confirm_keyboard,
    get_page_count_keyboard,
)
from bot.app.services.api_client import CourseForgeAPIClient
from shared.schemas.job import JobCreate

router = Router()


class GenerateForm(StatesGroup):
    """FSM states for the generation flow."""

    waiting_topic = State()
    waiting_discipline = State()
    waiting_university = State()
    waiting_page_count = State()
    waiting_instructions = State()
    waiting_confirmation = State()


@router.message(Command("generate"))
async def cmd_generate(message: Message, state: FSMContext) -> None:
    """Start the generation flow."""
    await state.clear()
    await state.set_state(GenerateForm.waiting_topic)
    await message.answer(
        "Введите тему курсовой работы:\n\n"
        "Например: «Влияние цифровизации на управление персоналом "
        "в российских компаниях»"
    )


@router.message(GenerateForm.waiting_topic)
async def process_topic(message: Message, state: FSMContext) -> None:
    """Receive the topic."""
    if not message.text or len(message.text) < 5:
        await message.answer("Тема слишком короткая. Введите более подробную тему (минимум 5 символов).")
        return

    await state.update_data(topic=message.text)
    await state.set_state(GenerateForm.waiting_discipline)
    await message.answer(
        "Укажите дисциплину (или отправьте «-» чтобы пропустить):\n\n"
        "Например: «Менеджмент», «Экономика», «Информатика»"
    )


@router.message(GenerateForm.waiting_discipline)
async def process_discipline(message: Message, state: FSMContext) -> None:
    """Receive the discipline."""
    text = message.text or ""
    discipline = "" if text.strip() == "-" else text.strip()
    await state.update_data(discipline=discipline)
    await state.set_state(GenerateForm.waiting_university)
    await message.answer(
        "Укажите университет (или отправьте «-» чтобы пропустить):\n\n"
        "Это поможет подобрать правильное форматирование."
    )


@router.message(GenerateForm.waiting_university)
async def process_university(message: Message, state: FSMContext) -> None:
    """Receive the university."""
    text = message.text or ""
    university = "" if text.strip() == "-" else text.strip()
    await state.update_data(university=university)
    await state.set_state(GenerateForm.waiting_page_count)
    await message.answer(
        "Выберите количество страниц:",
        reply_markup=get_page_count_keyboard(),
    )


@router.callback_query(GenerateForm.waiting_page_count, F.data.startswith("pages:"))
async def process_page_count(callback: CallbackQuery, state: FSMContext) -> None:
    """Receive page count from inline keyboard."""
    page_count = int(callback.data.split(":")[1])
    await state.update_data(page_count=page_count)
    await state.set_state(GenerateForm.waiting_instructions)
    await callback.message.edit_text(f"Количество страниц: {page_count}")
    await callback.message.answer(
        "Есть дополнительные требования? (или отправьте «-» чтобы пропустить)\n\n"
        "Например: «Обязательно рассмотреть зарубежный опыт», "
        "«Включить анализ статистики за последние 5 лет»"
    )


@router.message(GenerateForm.waiting_instructions)
async def process_instructions(message: Message, state: FSMContext) -> None:
    """Receive additional instructions."""
    text = message.text or ""
    instructions = "" if text.strip() == "-" else text.strip()
    await state.update_data(additional_instructions=instructions)

    # Show confirmation
    data = await state.get_data()
    summary = (
        f"📋 Подтвердите параметры:\n\n"
        f"📝 Тема: {data['topic']}\n"
        f"📚 Дисциплина: {data.get('discipline') or 'не указана'}\n"
        f"🏫 Университет: {data.get('university') or 'не указан'}\n"
        f"📄 Страниц: {data['page_count']}\n"
        f"💬 Доп. требования: {data.get('additional_instructions') or 'нет'}"
    )

    await state.set_state(GenerateForm.waiting_confirmation)
    await message.answer(summary, reply_markup=get_confirm_keyboard())


@router.callback_query(GenerateForm.waiting_confirmation, F.data == "confirm:yes")
async def process_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: CourseForgeAPIClient,
) -> None:
    """User confirmed — create the job."""
    data = await state.get_data()
    await state.clear()

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Запускаю генерацию... Это займёт 5-15 минут.")

    try:
        job_create = JobCreate(
            topic=data["topic"],
            discipline=data.get("discipline", ""),
            university=data.get("university", ""),
            page_count=data["page_count"],
            additional_instructions=data.get("additional_instructions", ""),
            telegram_id=callback.from_user.id,
        )
        job = await api_client.create_job(job_create)

        await callback.message.answer(
            f"Задание создано! ID: {job.id}\n\n"
            f"Используйте /status для проверки прогресса."
        )
    except Exception as e:
        await callback.message.answer(
            f"Ошибка при создании задания: {e}\n"
            f"Попробуйте позже или обратитесь в поддержку."
        )


@router.callback_query(GenerateForm.waiting_confirmation, F.data == "confirm:no")
async def process_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """User cancelled."""
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Генерация отменена. Отправьте /generate чтобы начать заново.")
