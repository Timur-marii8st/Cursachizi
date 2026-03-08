"""Payment-related keyboard layouts."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from shared.schemas.payment import CREDIT_PACKAGES


def get_packages_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for selecting a credit package."""
    buttons = []
    for pkg in CREDIT_PACKAGES:
        label = f"{pkg.label} — {pkg.price_rub} RUB"
        if pkg.credits > 1:
            label += f" ({pkg.price_per_credit} RUB/шт)"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"buy:{pkg.id}")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_payment_link_keyboard(payment_url: str) -> InlineKeyboardMarkup:
    """Keyboard with a link to Robokassa payment page."""
    buttons = [
        [InlineKeyboardButton(text="Оплатить", url=payment_url)],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_offer_keyboard(api_base_url: str) -> InlineKeyboardMarkup:
    """Keyboard with a link to download the public offer."""
    buttons = [
        [InlineKeyboardButton(text="Публичная оферта", url=f"{api_base_url}/api/offer")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
