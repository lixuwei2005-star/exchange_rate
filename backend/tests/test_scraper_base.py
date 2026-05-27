from __future__ import annotations

from decimal import Decimal

import pytest

from app.scrapers.base import Scraper, ScraperError, ScrapeResult


def test_scrape_result_validates_happy_path():
    r = ScrapeResult(
        base_currency="CNY",
        quote_currency="MYR",
        rate=Decimal("0.65"),
        rate_type="midmarket",
        raw_payload={"foo": "bar"},
    )
    assert r.rate == Decimal("0.65")
    assert r.rate_type == "midmarket"
    assert r.fee_estimate is None


def test_scrape_result_rejects_bad_rate_type():
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        ScrapeResult(
            base_currency="CNY",
            quote_currency="MYR",
            rate=Decimal("0.65"),
            rate_type="not-a-real-type",  # type: ignore[arg-type]
            raw_payload={},
        )


def test_sanity_check_rejects_out_of_range_cny_myr():
    class Dummy(Scraper):
        channel_code = "dummy"

        async def fetch(self, base: str, quote: str) -> ScrapeResult:
            raise NotImplementedError

    d = Dummy()
    with pytest.raises(ScraperError):
        d._sanity_check(Decimal("2.0"))  # way too high for CNY->MYR
    with pytest.raises(ScraperError):
        d._sanity_check(Decimal("0.1"))  # way too low
    # In-range should not raise:
    d._sanity_check(Decimal("0.65"))
