"""Coursework and article generation flow handlers using FSM (Finite State Machine)."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.app.keyboards.inline import (
    get_confirm_keyboard,
    get_page_count_keyboard,
    get_plan_question_keyboard,
    get_source_count_keyboard,
    get_work_type_keyboard,
)
from bot.app.services.api_client import CourseForgeAPIClient
from shared.schemas.job import JobCreate, WorkType

router = Router()

_WORK_TYPE_LABELS = {
    WorkType.COURSEWORK: "Курсовая работа",
    WorkType.ARTICLE: "Научная статья",
}


class GenerateForm(StatesGroup):
    """FSM states for the generation flow."""

    waiting_work_type = State()
    waiting_topic = State()
    waiting_discipline = State()
    waiting_university = State()
    waiting_page_count = State()
    waiting_source_count = State()
    waiting_plan_question = State()
    waiting_plan_text = State()
    waiting_instructions = State()
    waiting_confirmation = State()


@router.message(Command("generate"))
async def cmd_generate(message: Message, state: FSMContext) -> None:
    """Start the generation flow by asking for work type."""
    await state.clear()
    await state.set_state(GenerateForm.waiting_work_type)
    await message.answer(
        "Выберите тип работы:",
        reply_markup=get_work_type_keyboard(),
    )


@router.callback_query(GenerateForm.waiting_work_type, F.data.startswith("worktype:"))
async def process_work_type(callback: CallbackQuery, state: FSMContext) -> None:
    """Receive work type selection."""
    parts = callback.data.split(":", 1)
    try:
        work_type = WorkType(parts[1] if len(parts) > 1 else "")
    except ValueError:
        await callback.answer("Неверный выбор. Попробуйте снова.")
        return
    label = _WORK_TYPE_LABELS[work_type]

    await state.update_data(work_type=work_type.value)
    await state.set_state(GenerateForm.waiting_topic)
    await callback.message.edit_text(f"Тип работы: {label}")

    topic_hint = (
        "«Влияние цифровизации на управление персоналом в российских компаниях»"
        if work_type == WorkType.COURSEWORK
        else "«Методы машинного обучения в задачах классификации текста»"
    )
    await callback.message.answer(
        f"Введите тему {label.lower()}:\n\nНапример: {topic_hint}"
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

    data = await state.get_data()
    work_type = WorkType(data.get("work_type", WorkType.COURSEWORK.value))

    await state.set_state(GenerateForm.waiting_page_count)
    await message.answer(
        "Выберите количество страниц:",
        reply_markup=get_page_count_keyboard(work_type),
    )


@router.callback_query(GenerateForm.waiting_page_count, F.data.startswith("pages:"))
async def process_page_count(callback: CallbackQuery, state: FSMContext) -> None:
    """Receive page count from inline keyboard."""
    parts = callback.data.split(":", 1)
    try:
        page_count = int(parts[1] if len(parts) > 1 else "")
    except ValueError:
        await callback.answer("Неверное количество страниц. Попробуйте снова.")
        return
    await state.update_data(page_count=page_count)
    await callback.message.edit_text(f"Количество страниц: {page_count}")

    data = await state.get_data()
    work_type = WorkType(data.get("work_type", WorkType.COURSEWORK.value))

    await state.set_state(GenerateForm.waiting_source_count)
    await callback.message.answer(
        "Выберите количество источников для библиографии:",
        reply_markup=get_source_count_keyboard(work_type),
    )


@router.callback_query(GenerateForm.waiting_source_count, F.data.startswith("sources:"))
async def process_source_count(callback: CallbackQuery, state: FSMContext) -> None:
    """Receive source count selection."""
    parts = callback.data.split(":", 1)
    try:
        source_count = int(parts[1]) if len(parts) > 1 else 0
        if source_count < 5 or source_count > 80:
            raise ValueError
    except (ValueError, IndexError):
        await callback.answer("Неверный выбор. Попробуйте снова.")
        return

    await state.update_data(source_count=source_count)
    await callback.message.edit_text(f"Источников: {source_count}")
    await state.set_state(GenerateForm.waiting_plan_question)
    await callback.message.answer(
        "У вас есть готовый план (оглавление) работы?",
        reply_markup=get_plan_question_keyboard(),
    )


@router.callback_query(GenerateForm.waiting_plan_question, F.data == "hasplan:yes")
async def process_plan_yes(callback: CallbackQuery, state: FSMContext) -> None:
    """User has a custom plan — ask them to send it."""
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.set_state(GenerateForm.waiting_plan_text)
    await callback.message.answer(
        "Отправьте ваш план (оглавление) одним сообщением.\n\n"
        "Например:\n"
        "Глава 1. Теоретические основы\n"
        "1.1. Основные понятия\n"
        "1.2. Обзор литературы\n"
        "Глава 2. Практическая часть\n"
        "2.1. Методология\n"
        "2.2. Результаты"
    )


@router.callback_query(GenerateForm.waiting_plan_question, F.data == "hasplan:no")
async def process_plan_no(callback: CallbackQuery, state: FSMContext) -> None:
    """User doesn't have a plan — skip to instructions."""
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.update_data(custom_outline="")
    await state.set_state(GenerateForm.waiting_instructions)
    await callback.message.answer(
        "Есть дополнительные требования к работе?\n\n"
        "Например: «Обязательно рассмотреть зарубежный опыт», "
        "«Включить анализ статистики за последние 5 лет»\n\n"
        "Отправьте «-» чтобы пропустить."
    )


@router.message(GenerateForm.waiting_plan_question)
async def process_plan_question_text(message: Message, state: FSMContext) -> None:
    """Handle text input when buttons are expected."""
    await message.answer(
        "Пожалуйста, используйте кнопки выше для ответа.",
        reply_markup=get_plan_question_keyboard(),
    )


@router.message(GenerateForm.waiting_plan_text)
async def process_plan_text(message: Message, state: FSMContext) -> None:
    """Receive the custom outline text."""
    if not message.text or len(message.text) < 10:
        await message.answer("План слишком короткий. Отправьте более подробный план (минимум 10 символов).")
        return

    if len(message.text) > 3000:
        await message.answer(
            f"План слишком длинный ({len(message.text)} симв.). Максимум 3000 символов."
        )
        return

    await state.update_data(custom_outline=message.text)
    await state.set_state(GenerateForm.waiting_instructions)
    await message.answer(
        "Есть дополнительные требования к работе?\n\n"
        "Например: «Обязательно рассмотреть зарубежный опыт», "
        "«Включить анализ статистики за последние 5 лет»\n\n"
        "Отправьте «-» чтобы пропустить."
    )


@router.message(GenerateForm.waiting_instructions)
async def process_instructions(message: Message, state: FSMContext) -> None:
    """Receive additional instructions."""
    text = message.text or ""
    instructions = "" if text.strip() == "-" else text.strip()
    await state.update_data(additional_instructions=instructions)

    # Show confirmation
    data = await state.get_data()
    work_type = WorkType(data.get("work_type", WorkType.COURSEWORK.value))
    work_label = _WORK_TYPE_LABELS[work_type]

    summary = (
        f"📋 Подтвердите параметры:\n\n"
        f"🗂 Тип работы: {work_label}\n"
        f"📝 Тема: {data['topic']}\n"
        f"📚 Дисциплина: {data.get('discipline') or 'не указана'}\n"
        f"🏫 Университет: {data.get('university') or 'не указан'}\n"
        f"📄 Страниц: {data['page_count']}\n"
        f"📖 Источников: {data.get('source_count', 20)}\n"
        f"📐 План: {'предоставлен' if data.get('custom_outline') else 'будет сгенерирован'}\n"
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

    work_type = WorkType(data.get("work_type", WorkType.COURSEWORK.value))
    work_label = _WORK_TYPE_LABELS[work_type]

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"Запускаю генерацию {work_label.lower()}... Это займёт 5-15 минут."
    )

    try:
        job_create = JobCreate(
            work_type=work_type,
            topic=data["topic"],
            discipline=data.get("discipline", ""),
            university=data.get("university", ""),
            page_count=data["page_count"],
            source_count=data.get("source_count", 20),
            custom_outline=data.get("custom_outline", ""),
            additional_instructions=data.get("additional_instructions", ""),
            telegram_id=callback.from_user.id,
        )
        job = await api_client.create_job(job_create)
        await state.clear()  # Only clear state after the API call succeeds

        await callback.message.answer(
            f"Задание создано! ID: {job.id}\n\n"
            f"Используйте /status для проверки прогресса."
        )
    except RuntimeError as exc:
        # State is preserved — user can tap "Подтвердить" again to retry
        await callback.message.answer(
            f"Ошибка при создании задания: {exc}\n"
            f"Попробуйте позже или обратитесь в поддержку."
        )
    except Exception:
        await callback.message.answer(
            "Ошибка при создании задания. Попробуйте позже или обратитесь в поддержку."
        )


@router.callback_query(GenerateForm.waiting_confirmation, F.data == "confirm:no")
async def process_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """User cancelled."""
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Генерация отменена. Отправьте /generate чтобы начать заново.")
