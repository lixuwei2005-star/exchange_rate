from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, ClassVar

from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import RequestException

from app.scrapers._common import to_decimal
from app.scrapers.base import Scraper, ScraperError, ScrapeResult

# Visa MY's www host sits behind Cloudflare's anti-bot challenge ("Just a
# moment..." JS interstitial). Plain httpx from OCI gets HTTP 403 with the
# challenge page; curl_cffi can impersonate a real Chrome TLS/HTTP2
# fingerprint and pass straight through. Chrome 124 verified 2026-05-28.
# # TODO recheck-2026-11
IMPERSONATE = "chrome124"

# Browser-shape Accept headers; Referer matches the public calculator page
# that the cmsapi endpoint backs.
REFERER = "https://www.visa.com.my/support/consumer/travel-support/exchange-rate-calculator.html"
HEADERS: dict[str, str] = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": REFERER,
}


class VisaScraper(Scraper):
    """Visa exchange-rate calculator JSON endpoint.

    URL: https://www.visa.com.my/cmsapi/fx/rates

    The endpoint backs the public widget at
    /support/consumer/travel-support/exchange-rate-calculator.html .
    Cloudflare protects the host; curl_cffi (Chrome impersonation) bypasses
    cleanly. The response shape we care about:

        {
          "originalValues": {
            "fromCurrency": "MYR" | "CNY",
            "toCurrency":   "CNY" | "MYR",
            "fxRateVisa":   "1.7116421289",  # 1 fromCurrency = X toCurrency
            ...
          },
          ...
        }

    Quirk: Visa's API silently swaps the from/to we pass in the query, so
    `originalValues.fromCurrency` may NOT match what we sent. We always
    trust the labels in `originalValues` and invert the rate when the
    response's direction is opposite of what the caller asked for.

    No issuer markup is applied (CLAUDE.md §6 — homepage shows pure channel
    rates only; user decides which card / which issuer fee separately).
    The stored rate is therefore Visa's published network rate, in
    quote-per-base form.
    """

    channel_code: ClassVar[str] = "visa"
    timeout_seconds: ClassVar[int] = 20
    BASE_URL: ClassVar[str] = "https://www.visa.com.my/cmsapi/fx/rates"

    async def fetch(self, base: str, quote: str) -> ScrapeResult:
        if quote != "MYR":
            # Sanity range below assumes CNY->MYR; refactor if we add more pairs.
            raise ScraperError(f"visa: only MYR quote is configured (got {quote})")
        if base != "CNY":
            raise ScraperError(f"visa: only CNY base is configured (got {base})")
        today = date.today().strftime("%m/%d/%Y")
        params = {
            "amount": "1",
            "fee": "0",
            "fromCurr": base,
            "toCurr": quote,
            "utcConvertedDate": today,
            "exchangedate": today,
        }
        payload = await self._fetch_json(params)
        return self._parse(payload, base=base, quote=quote)

    async def _fetch_json(self, params: dict[str, str]) -> dict[str, Any]:
        try:
            async with AsyncSession(impersonate=IMPERSONATE) as client:
                resp = await client.get(
                    self.BASE_URL,
                    params=params,
                    headers=HEADERS,
                    timeout=self.timeout_seconds,
                )
                status = resp.status_code
                # Cloudflare's challenge serves HTTP 403 with an HTML body.
                # If we ever see that despite impersonation, surface a clearer
                # error so we know the fingerprint stopped working.
                if status == 403:
                    text = resp.text or ""
                    hint = ""
                    if "Just a moment" in text or "challenges.cloudflare.com" in text:
                        hint = " — Cloudflare challenge page; the curl_cffi fingerprint may be outdated"
                    raise ScraperError(f"visa: HTTP 403 from cmsapi{hint}")
                if status >= 400:
                    raise ScraperError(f"visa: HTTP {status} from cmsapi")
                try:
                    return resp.json()  # type: ignore[no-any-return]
                except Exception as exc:
                    raise ScraperError(f"visa: response is not JSON: {exc}") from exc
        except RequestException as exc:
            raise ScraperError(f"visa: HTTP error: {exc}") from exc

    # ---- pure parser --------------------------------------------------

    def _parse(self, payload: dict[str, Any], *, base: str, quote: str) -> ScrapeResult:
        """Extract rate from the Visa cmsapi payload, normalized to
        quote-per-1-base. Pure function — no network — so it's the testable
        seam."""
        ov = payload.get("originalValues") if isinstance(payload, dict) else None
        if not isinstance(ov, dict):
            raise ScraperError(f"visa: missing originalValues in payload: {payload!r}")

        ov_from = ov.get("fromCurrency")
        ov_to = ov.get("toCurrency")
        raw_rate = ov.get("fxRateVisa")
        if not isinstance(ov_from, str) or not isinstance(ov_to, str):
            raise ScraperError(f"visa: from/to currency missing in originalValues: {ov!r}")
        if raw_rate is None:
            raise ScraperError(f"visa: fxRateVisa missing in originalValues: {ov!r}")

        try:
            network_rate = to_decimal(raw_rate)
        except Exception as exc:
            raise ScraperError(f"visa: cannot parse fxRateVisa {raw_rate!r}: {exc}") from exc
        if network_rate <= 0:
            raise ScraperError(f"visa: non-positive fxRateVisa {network_rate}")

        # `network_rate` is "1 ov_from = X ov_to" per Visa's own labels. We
        # need "1 base = X quote". Three cases:
        if ov_from == base and ov_to == quote:
            rate = network_rate
            direction = "natural"
        elif ov_from == quote and ov_to == base:
            # Visa flipped the orientation (their known cmsapi quirk).
            # Invert with enough precision to preserve the 10-digit fxRateVisa.
            rate = (Decimal("1") / network_rate).quantize(Decimal("0.0000000001"))
            direction = "inverted"
        else:
            raise ScraperError(
                f"visa: unexpected pair in originalValues: "
                f"{ov_from!r} -> {ov_to!r} (asked {base} -> {quote})"
            )

        rate = rate.quantize(Decimal("0.00000001"))
        if base == "CNY" and quote == "MYR":
            self._sanity_check(rate)

        return ScrapeResult(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            rate_type="card_network",
            raw_payload={
                "network_rate": str(network_rate),
                "ov_from": ov_from,
                "ov_to": ov_to,
                "direction": direction,
                "as_of_date": ov.get("asOfDate"),
                "last_updated_visa_rate": ov.get("lastUpdatedVisaRate"),
                "raw": payload,
            },
            fee_estimate=None,
            fee_currency=None,
        )
