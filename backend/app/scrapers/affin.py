from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar

import httpx

from app.scrapers.base import Scraper, ScraperError, ScrapeResult

# Affin Bank (Malaysia). The rates page is a JS carousel, but it just renders
# static JSON files the bank publishes under /storage/rates/. We hit the JSON
# directly — plain GET + project UA, HTTP 200, no bot wall (verified
# 2026-05-30). The per-100-unit feed holds CNY.
PROJECT_HEADERS: dict[str, str] = {
    "User-Agent": "rate.005917.xyz contact: lixuwei2005@gmail.com",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

# CNY is quoted per 100 units → divide by this. (The feed filename literally
# says "100-unit"; we still divide explicitly so the convention is in code.)
MULTIPLIER = 100
_UNAVAILABLE = {"", "-", "--", "n/a", "na"}


class AffinScraper(Scraper):
    """Affin Bank (Malaysia) foreign-exchange board, via its static JSON feed.

    Feed: https://www.affinalways.com/storage/rates/forex-100-unit.json
    Each entry: {"currency": "CHINESE RENMINBI", "code": "(CNY)",
                 "selling": {"ttod": 60.6}, "buying": {"tt": 56.6, "od": "N/A"}}

    Rates are MYR per 100 foreign units. For CNY → MYR the customer hands CNY
    to the bank and gets MYR — the bank BUYS CNY — so we use **buying.tt** ÷ 100.
    (Affin publishes only 1 decimal place, so this rate is coarser than the
    other banks — that's the source's precision, not ours.)

    Fee model: fee_estimate is None — the spread is already in buying.tt.
    """

    channel_code: ClassVar[str] = "affin"
    timeout_seconds: ClassVar[int] = 15
    URL: ClassVar[str] = "https://www.affinalways.com/storage/rates/forex-100-unit.json"
    DATE_URL: ClassVar[str] = "https://www.affinalways.com/storage/rates/forex-date.json"

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        if quote != "MYR":
            raise ScraperError(f"affin: only MYR quote is configured (got {quote})")
        if base != "CNY":
            raise ScraperError(f"affin: only CNY base is configured (got {base})")

        async with httpx.AsyncClient(
            timeout=self.timeout_seconds, headers=PROJECT_HEADERS, follow_redirects=True
        ) as client:
            try:
                resp = await client.get(self.URL)
                resp.raise_for_status()
                payload = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise ScraperError(f"affin: HTTP error: {exc}") from exc
            # Best-effort "as at" timestamp; never fatal.
            as_at: str | None = None
            try:
                d = (await client.get(self.DATE_URL)).json()
                if isinstance(d, list) and d and isinstance(d[0], dict):
                    as_at = d[0].get("date")
            except Exception:  # noqa: BLE001 — timestamp is decorative
                as_at = None

        return self._parse(payload, base=base, quote=quote, as_at=as_at)

    # ---- pure parser --------------------------------------------------

    def _parse(
        self, payload: Any, *, base: str, quote: str, as_at: str | None = None
    ) -> ScrapeResult:
        if not isinstance(payload, list):
            raise ScraperError(f"affin: expected a JSON list, got {type(payload).__name__}")

        entry = self._find_cny(payload)
        if entry is None:
            raise ScraperError("affin: no CNY entry in forex-100-unit feed")

        buying = entry.get("buying")
        if not isinstance(buying, dict):
            raise ScraperError(f"affin: CNY entry missing 'buying' object: {entry!r}")
        tt_raw = buying.get("tt")
        if tt_raw is None or str(tt_raw).strip().lower() in _UNAVAILABLE:
            raise ScraperError(f"affin: CNY buying.tt is unavailable ({tt_raw!r})")

        try:
            tt = Decimal(str(tt_raw).replace(",", ""))
        except InvalidOperation as exc:
            raise ScraperError(f"affin: cannot parse buying.tt {tt_raw!r}: {exc}") from exc
        if tt <= 0:
            raise ScraperError(f"affin: buying.tt is {tt_raw!r} (zero) for CNY")

        rate = (tt / Decimal(MULTIPLIER)).quantize(Decimal("0.00000001"))
        if base == "CNY" and quote == "MYR":
            self._sanity_check(rate)

        selling = entry.get("selling") if isinstance(entry.get("selling"), dict) else {}
        return ScrapeResult(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            rate_type="tt_buy",
            raw_payload={
                "buying_tt": str(tt_raw),
                "buying_od": buying.get("od"),
                "selling_ttod": selling.get("ttod") if isinstance(selling, dict) else None,
                "multiplier": MULTIPLIER,
                "code": entry.get("code"),
                "as_at": as_at,
            },
            fee_estimate=None,
            fee_currency=None,
        )

    @staticmethod
    def _find_cny(items: list[Any]) -> dict[str, Any] | None:
        for it in items:
            if not isinstance(it, dict):
                continue
            code = str(it.get("code", "")).strip("() ").upper()
            name = str(it.get("currency", "")).upper()
            if code == "CNY" or "CHINESE RENMINBI" in name:
                return it
        return None
