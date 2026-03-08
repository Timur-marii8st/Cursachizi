"""Payment and credit management handlers."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.app.config import get_bot_settings
from bot.app.keyboards.payment import (
    get_offer_keyboard,
    get_packages_keyboard,
    get_payment_link_keyboard,
)
from bot.app.services.api_client import CourseForgeAPIClient
from shared.schemas.payment import PACKAGES_BY_ID, PaymentCreate

router = Router()


@router.message(Command("buy"))
async def cmd_buy(message: Message, api_client: CourseForgeAPIClient) -> None:
    """Show available credit packages."""
    if not message.from_user:
        return

    try:
        balance = await api_client.get_balance(message.from_user.id)
        balance_text = f"Ваш баланс: {balance.credits_remaining} кредит(ов)\n\n"
    except Exception:
        balance_text = ""

    await message.answer(
        f"{balance_text}"
        "Выберите пакет кредитов:\n"
        "(1 кредит = 1 курсовая работа)",
        reply_markup=get_packages_keyboard(),
    )


@router.callback_query(F.data.startswith("buy:"))
async def process_buy(
    callback: CallbackQuery,
    api_client: CourseForgeAPIClient,
) -> None:
    """Handle package selection — create payment and show link."""
    if not callback.from_user or not callback.message:
        return

    package_id = callback.data.split(":")[1]
    package = PACKAGES_BY_ID.get(package_id)
    if not package:
        await callback.answer("Неизвестный пакет", show_alert=True)
        return

    try:
        payment = await api_client.create_payment(
            PaymentCreate(
                package_id=package_id,
                telegram_id=callback.from_user.id,
            )
        )
    except Exception as e:
        await callback.message.answer(f"Ошибка при создании платежа: {e}")
        return

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"Заказ #{payment.id}\n"
        f"Пакет: {package.label}\n"
        f"Сумма: {package.price_rub} RUB\n\n"
        f"Нажмите кнопку для перехода к оплате:",
        reply_markup=get_payment_link_keyboard(payment.payment_url),
    )


@router.message(Command("balance"))
async def cmd_balance(message: Message, api_client: CourseForgeAPIClient) -> None:
    """Show current credit balance."""
    if not message.from_user:
        return

    try:
        balance = await api_client.get_balance(message.from_user.id)
        await message.answer(
            f"Ваш баланс: {balance.credits_remaining} кредит(ов)\n"
            f"Всего сгенерировано работ: {balance.total_papers_generated}\n\n"
            f"Для пополнения используйте /buy"
        )
    except Exception as e:
        await message.answer(f"Не удалось получить баланс: {e}")


@router.message(Command("offer"))
async def cmd_offer(message: Message) -> None:
    """Show link to public offer document."""
    settings = get_bot_settings()
    await message.answer(
        "Публичная оферта — договор на оказание услуг по генерации учебных материалов.",
        reply_markup=get_offer_keyboard(settings.api_base_url),
    )
