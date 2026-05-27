from __future__ import annotations

from decimal import Decimal

from app.services.conversion import apply_fees


def test_apply_fees_midmarket_no_fee():
    # 1000 CNY * 0.65 = 650 MYR
    out = apply_fees("midmarket", Decimal("1000"), Decimal("0.65"))
    assert out == Decimal("650.00")


def test_apply_fees_boc_flat_cny():
    # 1000 - 50 fee = 950 CNY; 950 * 0.65 = 617.5 MYR
    out = apply_fees("boc", Decimal("1000"), Decimal("0.65"))
    assert out == Decimal("617.50")


def test_apply_fees_maybank_flat_myr():
    # 1000 * 0.65 = 650 - 10 fee = 640 MYR
    out = apply_fees("maybank", Decimal("1000"), Decimal("0.65"))
    assert out == Decimal("640.00")


def test_apply_fees_floor_at_zero():
    # 30 CNY at BOC with 50 CNY flat fee -> nothing converts
    out = apply_fees("boc", Decimal("30"), Decimal("0.65"))
    assert out == Decimal("0")


def test_apply_fees_invalid_inputs():
    assert apply_fees("midmarket", Decimal("0"), Decimal("0.65")) == Decimal("0")
    assert apply_fees("midmarket", Decimal("1000"), Decimal("0")) == Decimal("0")
