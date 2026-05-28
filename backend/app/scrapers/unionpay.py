from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import ClassVar
from zoneinfo import ZoneInfo

import httpx

from app.scrapers._common import make_client
from app.scrapers.base import Scraper, ScraperError, ScrapeResult


class UnionPayScraper(Scraper):
    """UnionPay International cross-border rate, published as a static daily
    JSON file named by Beijing date — no auth, no form POST, no cookies.

        GET https://www.unionpayintl.com/upload/jfimg/{YYYYMMDD}.json

    The response has the shape:
        {"exchangeRateJson": [{"transCur": "MYR", "baseCur": "CNY",
                               "rateData": 1.71878002}, ...thousands more...]}

    Semantics: `1 transCur = rateData × baseCur`. For our CNY-billed card
    spending MYR in Malaysia we want the entry where transCur=MYR,
    baseCur=CNY — that value is CNY per 1 MYR. Our storage convention is
    MYR per 1 CNY, so we invert: stored_rate = 1 / rateData.

    Fee model (CLAUDE.md §6): UnionPay's published rate is a near-mid
    composite with no built-in markup. The real 1–2% cost users see is an
    issuer-dependent fee added on top, which we do NOT model in V1, so
    fee_estimate is None.

    Date logic:
      - MYR is a non-European currency; UnionPay locks its rate at 11:00
        Beijing time. Scrape after that.
      - Today's file (Asia/Shanghai date) may 404 if not published yet, so
        on 404 step back one day, up to 3 days back.
    """

    channel_code: ClassVar[str] = "unionpay"
    timeout_seconds: ClassVar[int] = 20
    URL_TEMPLATE: ClassVar[str] = "https://www.unionpayintl.com/upload/jfimg/{date}.json"
    MAX_DAYS_BACK: ClassVar[int] = 3
    TIMEZONE: ClassVar[ZoneInfo] = ZoneInfo("Asia/Shanghai")

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        if base != "CNY":
            raise ScraperError(f"unionpay: only CNY base supported (got {base})")

        payload, file_date = await self._fetch_with_fallback()
        match = self._find_entry(payload, trans_cur=quote, base_cur=base)
        if match is None:
            raise ScraperError(
                f"unionpay: no entry with transCur={quote!r} baseCur={base!r} "
                f"in {file_date} file (total entries: "
                f"{len(payload.get('exchangeRateJson', []))})"
            )

        rate_data = match.get("rateData")
        if rate_data is None:
            raise ScraperError(f"unionpay: matched entry has no rateData: {match!r}")

        try:
            cny_per_quote = Decimal(str(rate_data))
        except Exception as exc:
            raise ScraperError(f"unionpay: cannot parse rateData {rate_data!r}: {exc}") from exc
        if cny_per_quote <= 0:
            raise ScraperError(f"unionpay: non-positive rateData {cny_per_quote}")

        rate = (Decimal("1") / cny_per_quote).quantize(Decimal("0.00000001"))
        self._sanity_check(rate)

        return ScrapeResult(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            rate_type="card_network",
            raw_payload={"file_date": file_date, "entry": match},
            # See class docstring: UnionPay's quote has no built-in markup, the
            # 1-2% real cost is issuer-dependent and not modeled in V1.
            fee_estimate=None,
            fee_currency=None,
        )

    async def _fetch_with_fallback(self) -> tuple[dict, str]:
        """GET today's file in Asia/Shanghai, falling back day-by-day on 404
        for up to MAX_DAYS_BACK days. Returns (parsed_json, YYYYMMDD_used)."""
        today_cn = datetime.now(self.TIMEZONE).date()
        last_404: str | None = None
        async with make_client(self.timeout_seconds) as client:
            for delta in range(self.MAX_DAYS_BACK + 1):
                date_str = (today_cn - timedelta(days=delta)).strftime("%Y%m%d")
                url = self.URL_TEMPLATE.format(date=date_str)
                try:
                    resp = await client.get(url)
                except httpx.HTTPError as exc:
                    raise ScraperError(f"unionpay: HTTP error fetching {url}: {exc}") from exc
                if resp.status_code == 404:
                    last_404 = date_str
                    continue
                if resp.status_code != 200:
                    raise ScraperError(f"unionpay: unexpected status {resp.status_code} for {url}")
                try:
                    payload = resp.json()
                except ValueError as exc:
                    raise ScraperError(f"unionpay: invalid JSON in {url}: {exc}") from exc
                if not isinstance(payload, dict):
                    raise ScraperError(
                        f"unionpay: expected object response from {url}, got "
                        f"{type(payload).__name__}"
                    )
                return payload, date_str
        raise ScraperError(
            f"unionpay: all {self.MAX_DAYS_BACK + 1} candidate dates returned 404 "
            f"(latest tried: {last_404})"
        )

    def _find_entry(self, payload: dict, *, trans_cur: str, base_cur: str) -> dict | None:
        arr = payload.get("exchangeRateJson")
        if not isinstance(arr, list):
            return None
        for entry in arr:
            if (
                isinstance(entry, dict)
                and entry.get("transCur") == trans_cur
                and entry.get("baseCur") == base_cur
            ):
                return entry
        return None
