"""Tests for payment schemas."""

import pytest

from shared.schemas.payment import (
    CREDIT_PACKAGES,
    PACKAGES_BY_ID,
    BalanceResponse,
    PaymentCreate,
    PaymentStatus,
)


class TestCreditPackages:
    def test_four_packages_defined(self):
        assert len(CREDIT_PACKAGES) == 4

    def test_prices_descending_per_credit(self):
        prices = [p.price_per_credit for p in CREDIT_PACKAGES]
        assert prices == sorted(prices, reverse=True)

    def test_all_packages_in_lookup(self):
        for pkg in CREDIT_PACKAGES:
            assert pkg.id in PACKAGES_BY_ID
            assert PACKAGES_BY_ID[pkg.id] is pkg

    def test_pack_1_is_199(self):
        assert PACKAGES_BY_ID["pack_1"].price_rub == 199
        assert PACKAGES_BY_ID["pack_1"].credits == 1

    def test_pack_10_bulk_discount(self):
        p10 = PACKAGES_BY_ID["pack_10"]
        p1 = PACKAGES_BY_ID["pack_1"]
        assert p10.price_per_credit < p1.price_per_credit


class TestPaymentCreate:
    def test_valid(self):
        pc = PaymentCreate(package_id="pack_3", telegram_id=123456)
        assert pc.package_id == "pack_3"
        assert pc.telegram_id == 123456

    def test_requires_telegram_id(self):
        with pytest.raises(Exception):
            PaymentCreate(package_id="pack_1")


class TestPaymentStatus:
    def test_enum_values(self):
        assert PaymentStatus.PENDING == "pending"
        assert PaymentStatus.COMPLETED == "completed"
        assert PaymentStatus.FAILED == "failed"


class TestBalanceResponse:
    def test_construction(self):
        b = BalanceResponse(
            telegram_id=42, credits_remaining=5, total_papers_generated=3,
        )
        assert b.credits_remaining == 5
