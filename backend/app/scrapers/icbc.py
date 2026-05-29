from __future__ import annotations

import ssl
from decimal import Decimal
from typing import Any, ClassVar

import httpx

from app.scrapers._common import UA, to_decimal
from app.scrapers.base import Scraper, ScraperError, ScrapeResult

# The public ICBC rate page (icbc.com.cn/column/...) is a Vue SPA that fetches
# its board from a JSON API, so we hit that API directly rather than render the
# page (verified 2026-05-29: POST returns HTTP 200 application/json, no auth,
# no bot wall). # TODO recheck-2026-11
API_URL = "https://papi.icbc.com.cn/exchanges/ns/getLatest"
# Look like the www.icbc.com.cn page that normally calls this endpoint.
POST_HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "zh-CN,en;q=0.8",
    "Content-Type": "application/json",
    "Origin": "https://www.icbc.com.cn",
    "Referer": "https://www.icbc.com.cn/column/1438058341489590354.html",
}


def _legacy_tls_context() -> ssl.SSLContext:
    """ICBC's papi host requires TLS legacy renegotiation, which OpenSSL 3
    disables by default (-> UNSAFE_LEGACY_RENEGOTIATION_DISABLED). Re-enable it
    for this host only; certificate verification stays on."""
    ctx = ssl.create_default_context()
    ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x04)
    return ctx


_SSL_CONTEXT = _legacy_tls_context()


class ICBCScraper(Scraper):
    """Industrial and Commercial Bank of China (工商银行) forex board.

    Source: POST https://papi.icbc.com.cn/exchanges/ns/getLatest
        -> {"code":0,"data":[{"currencyENName":"MYR","foreignSell":"171.38",
            "foreignBuy":"169.81","reference":"170.66","publishDate":...}, ...]}

    `foreignSell` is 现汇卖出价 — the bank SELLS MYR to the customer for CNY
    (CLAUDE.md §2.4) — quoted as CNY per 100 MYR, same basis as BOC. For
    CNY -> MYR the stored direction is MYR per 1 CNY, so:

        rate = 100 / foreignSell

    Fee model: fee_estimate is None — the spread is already in 现汇卖出价.
    """

    channel_code: ClassVar[str] = "icbc"
    timeout_seconds: ClassVar[int] = 20
    URL: ClassVar[str] = API_URL

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        if base != "CNY":
            raise ScraperError(f"icbc: only CNY base is supported (got {base})")
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                verify=_SSL_CONTEXT,
                follow_redirects=True,
            ) as client:
                resp = await client.post(self.URL, content=b"", headers=POST_HEADERS)
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPError as exc:
            raise ScraperError(f"icbc: HTTP error: {exc}") from exc
        except ValueError as exc:
            raise ScraperError(f"icbc: response was not valid JSON: {exc}") from exc

        return self._parse(payload, base=base, quote=quote)

    # ---- pure parser --------------------------------------------------

    def _parse(self, payload: Any, *, base: str, quote: str) -> ScrapeResult:
        if not isinstance(payload, dict) or payload.get("code") != 0:
            raise ScraperError("icbc: unexpected payload (missing code==0)")
        data = payload.get("data")
        if not isinstance(data, list):
            raise ScraperError("icbc: payload.data is not a list")

        entry = self._find_currency(data, quote)
        if entry is None:
            raise ScraperError(f"icbc: no entry for {quote} in getLatest data")

        raw = entry.get("foreignSell")
        if raw in (None, "", "--"):
            raise ScraperError(f"icbc: 现汇卖出价 (foreignSell) unavailable for {quote}: {raw!r}")
        try:
            ask_per_100 = to_decimal(raw)
        except Exception as exc:
            raise ScraperError(f"icbc: cannot parse foreignSell {raw!r}: {exc}") from exc
        if ask_per_100 <= 0:
            raise ScraperError(f"icbc: non-positive foreignSell {ask_per_100}")

        # CNY per 100 quote -> MYR per 1 CNY
        rate = (Decimal("100") / ask_per_100).quantize(Decimal("0.00000001"))
        if base == "CNY" and quote == "MYR":
            self._sanity_check(rate)

        return ScrapeResult(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            rate_type="bank_ask",
            raw_payload={
                "foreign_sell_per_100": str(ask_per_100),
                "reference": entry.get("reference"),
                "publish_date": entry.get("publishDate"),
                "publish_time": entry.get("publishTime"),
                "source": "icbc getLatest",
            },
            fee_estimate=None,
            fee_currency=None,
        )

    @staticmethod
    def _find_currency(data: list[Any], quote: str) -> dict[str, Any] | None:
        for item in data:
            if isinstance(item, dict) and item.get("currencyENName") == quote:
                return item
        return None
