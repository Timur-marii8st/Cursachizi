"""Tests for Robokassa payment integration."""

import hashlib

import pytest

from backend.app.services.robokassa import (
    _signature,
    generate_payment_link,
    verify_result_signature,
    verify_success_signature,
)


class TestSignature:
    def test_basic(self):
        result = _signature("login", 100, 1, "password")
        expected = hashlib.md5("login:100:1:password".encode()).hexdigest()
        assert result == expected

    def test_consistent(self):
        assert _signature("a", "b", "c") == _signature("a", "b", "c")

    def test_different_args(self):
        assert _signature("a", "b") != _signature("a", "c")


class TestGeneratePaymentLink:
    def test_contains_required_params(self):
        url = generate_payment_link(
            merchant_login="demo",
            password1="pass1",
            cost=199,
            inv_id=42,
            description="Test payment",
            is_test=True,
        )
        assert "MerchantLogin=demo" in url
        assert "OutSum=199" in url
        assert "InvId=42" in url
        assert "IsTest=1" in url
        assert "SignatureValue=" in url
        assert "auth.robokassa.ru" in url

    def test_production_mode(self):
        url = generate_payment_link(
            merchant_login="demo",
            password1="pass1",
            cost=100,
            inv_id=1,
            description="Test",
            is_test=False,
        )
        assert "IsTest=0" in url

    def test_description_encoded(self):
        url = generate_payment_link(
            merchant_login="demo",
            password1="pass1",
            cost=100,
            inv_id=1,
            description="CourseForge: 3 кредита",
            is_test=True,
        )
        # URL-encoded description
        assert "Description=" in url


class TestVerifyResultSignature:
    def test_valid_signature(self):
        password2 = "secret2"
        out_sum = "199"
        inv_id = "42"
        sig = hashlib.md5(f"{out_sum}:{inv_id}:{password2}".encode()).hexdigest()

        assert verify_result_signature(password2, out_sum, inv_id, sig) is True

    def test_invalid_signature(self):
        assert verify_result_signature("secret2", "199", "42", "bad_sig") is False

    def test_case_insensitive(self):
        password2 = "secret2"
        out_sum = "100"
        inv_id = "1"
        sig = hashlib.md5(f"{out_sum}:{inv_id}:{password2}".encode()).hexdigest()

        assert verify_result_signature(password2, out_sum, inv_id, sig.upper()) is True


class TestVerifySuccessSignature:
    def test_valid_signature(self):
        password1 = "secret1"
        out_sum = "199"
        inv_id = "42"
        sig = hashlib.md5(f"{out_sum}:{inv_id}:{password1}".encode()).hexdigest()

        assert verify_success_signature(password1, out_sum, inv_id, sig) is True

    def test_invalid_signature(self):
        assert verify_success_signature("secret1", "199", "42", "wrong") is False
