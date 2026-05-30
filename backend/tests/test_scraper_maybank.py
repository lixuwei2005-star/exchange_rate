"""Maybank scraper tests (Firecrawl-backed).

Maybank sits behind Akamai, so the scraper fetches the page through Firecrawl
(POST https://api.firecrawl.dev/v1/scrape) and parses the returned HTML itself.
The HTML is Maybank's server-rendered counter-rate table: the row label bakes
in the multiplier ("100 Chinese Renminbi") and the columns after it are
[Selling TT/OD, Buying TT, Buying OD, ...]. For CNY -> MYR we take Buying TT
(bank BUYS CNY) ÷ multiplier. Stored convention is MYR per 1 CNY.

The Firecrawl key is read from Settings.firecrawl_api_key; an empty key
short-circuits before any network call.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest
import respx

from app.config import Settings, get_settings
from app.scrapers.base import ScraperError
from app.scrapers.maybank import FIRECRAWL_ENDPOINT, MaybankScraper

FIXTURE_KEY = "fc-test-key-123"


@pytest.fixture(autouse=True)
def _patch_settings():
    """Inject a fake Firecrawl key into get_settings() for every test."""
    fake = Settings(
        fernet_key="jXV6ArgMcNyfMYx2bl6w2BQZtNsraEP2W0hs0HAVB6I=",
        jwt_secret="test-jwt-secret-padded-to-be-long-enough-for-hs256",
        firecrawl_api_key=FIXTURE_KEY,
    )
    get_settings.cache_clear()
    with patch("app.scrapers.maybank.get_settings", return_value=fake):
        yield
    get_settings.cache_clear()


def _table(rows: list[tuple[str, list[str]]]) -> str:
    """rows = [(label_cell, [numeric cells...]), ...]."""
    head = "<tr><th>Currency</th><th>Selling TT/OD</th>" "<th>Buying TT</th><th>Buying OD</th></tr>"
    body = ""
    for label, nums in rows:
        tds = "".join(f"<td>{n}</td>" for n in nums)
        body += f"<tr><td>{label}</td>{tds}</tr>"
    return f"<table>{head}{body}</table>"


def _page(rows: list[tuple[str, list[str]]]) -> str:
    return (
        "<!DOCTYPE html><html><body><main>"
        "<h2>Foreign Exchange Counter Rates</h2>"
        "<p>Last Update May 30, 2026 6:00 PM</p>"
        f"{_table(rows)}"
        "</main></body></html>"
    )


LIVE_ROWS: list[tuple[str, list[str]]] = [
    ("1 US Dollar", ["4.0730", "3.8690", "3.8500"]),
    ("100 Chinese Renminbi", ["61.5000", "56.1200", "56.0000"]),
]


def _firecrawl_ok(html: str, status: int = 200) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "success": True,
            "data": {"rawHtml": html, "metadata": {"statusCode": status}},
        },
    )


# ---- happy path (full fetch through Firecrawl) ------------------------


@pytest.mark.asyncio
@respx.mock
async def test_maybank_picks_cny_buy_tt_and_divides_by_multiplier():
    route = respx.post(FIRECRAWL_ENDPOINT).mock(return_value=_firecrawl_ok(_page(LIVE_ROWS)))

    r = await MaybankScraper().fetch("CNY", "MYR")

    # 56.1200 / 100 = 0.56120000
    assert r.rate == Decimal("0.56120000")
    assert Decimal("0.5") <= r.rate <= Decimal("0.8")
    assert r.rate_type == "tt_buy"
    assert r.fee_estimate is None
    assert r.raw_payload["multiplier"] == 100
    assert r.raw_payload["buying_tt"] == "56.1200"
    assert r.raw_payload["selling_tt_od"] == "61.5000"
    assert r.raw_payload["buying_od"] == "56.0000"
    assert r.raw_payload["rate_columns"] == ["61.5000", "56.1200", "56.0000"]
    assert r.raw_payload["via"] == "firecrawl"
    assert r.raw_payload["source_status_code"] == 200

    # The request must carry our auth + project UA, and ask for rawHtml.
    sent = route.calls.last.request
    assert sent.headers["Authorization"] == f"Bearer {FIXTURE_KEY}"
    assert "rate.005917.xyz" in sent.headers["User-Agent"]


# ---- key handling -----------------------------------------------------


@pytest.mark.asyncio
async def test_maybank_short_circuits_when_key_empty():
    """No HTTP call when the key is empty — keeps Firecrawl quota intact."""
    fake = Settings(
        fernet_key="jXV6ArgMcNyfMYx2bl6w2BQZtNsraEP2W0hs0HAVB6I=",
        jwt_secret="test-jwt-secret-padded-to-be-long-enough-for-hs256",
        firecrawl_api_key="",
    )
    with patch("app.scrapers.maybank.get_settings", return_value=fake):
        with pytest.raises(ScraperError, match="FIRECRAWL_API_KEY is not set"):
            await MaybankScraper().fetch("CNY", "MYR")


# ---- Firecrawl-side failures ------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_maybank_raises_on_firecrawl_success_false():
    respx.post(FIRECRAWL_ENDPOINT).mock(
        return_value=httpx.Response(200, json={"success": False, "error": "blocked"})
    )
    with pytest.raises(ScraperError, match="success=false"):
        await MaybankScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_maybank_raises_on_401():
    respx.post(FIRECRAWL_ENDPOINT).mock(return_value=httpx.Response(401, json={"error": "bad key"}))
    with pytest.raises(ScraperError, match="401"):
        await MaybankScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_maybank_raises_on_402_credits_exhausted():
    respx.post(FIRECRAWL_ENDPOINT).mock(
        return_value=httpx.Response(402, json={"error": "no credits"})
    )
    with pytest.raises(ScraperError, match="402|credits"):
        await MaybankScraper().fetch("CNY", "MYR")


@pytest.mark.asyncio
@respx.mock
async def test_maybank_raises_when_firecrawl_returns_no_html():
    respx.post(FIRECRAWL_ENDPOINT).mock(
        return_value=httpx.Response(200, json={"success": True, "data": {"metadata": {}}})
    )
    with pytest.raises(ScraperError, match="no rawHtml/html"):
        await MaybankScraper().fetch("CNY", "MYR")


# ---- pure parser ------------------------------------------------------


def test_maybank_parser_raises_on_challenge_page():
    """An Akamai interstitial lacks the rate-table marker."""
    junk = "<html><body><p>Pardon our interruption…</p></body></html>"
    with pytest.raises(ScraperError, match="missing the rate-table marker"):
        MaybankScraper()._parse(junk, base="CNY", quote="MYR", label_needle="Chinese Renminbi")


def test_maybank_parser_raises_when_cny_row_has_no_numbers():
    # Marker present (in the label) but the row has no numeric cells (N/A).
    html = _page([("100 Chinese Renminbi", ["N/A", "N/A"])])
    with pytest.raises(ScraperError, match="no row containing"):
        MaybankScraper()._parse(html, base="CNY", quote="MYR", label_needle="Chinese Renminbi")


def test_maybank_parser_raises_on_zero_buy_tt():
    html = _page([("100 Chinese Renminbi", ["61.5000", "0", "0"])])
    with pytest.raises(ScraperError, match="zero|unavailable"):
        MaybankScraper()._parse(html, base="CNY", quote="MYR", label_needle="Chinese Renminbi")


def test_maybank_parser_raises_on_out_of_range_rate():
    """If the multiplier is mis-read as 1, Buying TT 56.12 lands at 56.12 —
    must trip the [0.5, 0.8] sanity check rather than ship a 100x-wrong rate."""
    html = _page([("Chinese Renminbi", ["61.5000", "56.1200", "56.0000"])])  # no leading int
    with pytest.raises(ScraperError, match="sanity check failed"):
        MaybankScraper()._parse(html, base="CNY", quote="MYR", label_needle="Chinese Renminbi")


# ---- guard rails ------------------------------------------------------


@pytest.mark.asyncio
async def test_maybank_rejects_non_myr_quote():
    with pytest.raises(ScraperError, match="only MYR"):
        await MaybankScraper().fetch("CNY", "USD")


@pytest.mark.asyncio
async def test_maybank_rejects_non_cny_base():
    with pytest.raises(ScraperError, match="only CNY base"):
        await MaybankScraper().fetch("USD", "MYR")
