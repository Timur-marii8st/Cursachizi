"""Robokassa payment integration."""

import hashlib
from urllib import parse

import structlog

logger = structlog.get_logger()

ROBOKASSA_URL = "https://auth.robokassa.ru/Merchant/Index.aspx"


def _signature(*args: str | int | float) -> str:
    """Calculate MD5 signature from positional args joined by ':'."""
    raw = ":".join(str(a) for a in args)
    return hashlib.md5(raw.encode()).hexdigest()


def generate_payment_link(
    merchant_login: str,
    password1: str,
    cost: int,
    inv_id: int,
    description: str,
    is_test: bool = True,
) -> str:
    """Generate a Robokassa payment URL.

    Args:
        merchant_login: Robokassa MerchantLogin.
        password1: Robokassa Password #1.
        cost: Payment amount in RUB.
        inv_id: Invoice number (unique per payment).
        description: Payment description shown to user.
        is_test: Use test mode (no real charges).

    Returns:
        Full URL to redirect user to Robokassa payment page.
    """
    signature = _signature(merchant_login, cost, inv_id, password1)
    params = {
        "MerchantLogin": merchant_login,
        "OutSum": cost,
        "InvId": inv_id,
        "Description": description,
        "SignatureValue": signature,
        "IsTest": 1 if is_test else 0,
    }
    url = f"{ROBOKASSA_URL}?{parse.urlencode(params)}"
    logger.info("robokassa_link_generated", inv_id=inv_id, cost=cost, is_test=is_test)
    return url


def verify_result_signature(
    password2: str,
    out_sum: str,
    inv_id: str,
    signature_value: str,
) -> bool:
    """Verify the ResultURL callback signature from Robokassa.

    Robokassa sends a POST/GET to ResultURL with OutSum, InvId, SignatureValue.
    Signature = MD5(OutSum:InvId:Password2).
    """
    expected = _signature(out_sum, inv_id, password2)
    return expected.lower() == signature_value.lower()


def verify_success_signature(
    password1: str,
    out_sum: str,
    inv_id: str,
    signature_value: str,
) -> bool:
    """Verify the SuccessURL callback signature from Robokassa.

    Signature = MD5(OutSum:InvId:Password1).
    """
    expected = _signature(out_sum, inv_id, password1)
    return expected.lower() == signature_value.lower()
