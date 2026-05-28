"""Maybank end-to-end diagnostic. Runs the live scraper, prints a clear
verdict, and exits non-zero on failure so you can chain it from shell.

Usage on the server:
    docker compose -f docker-compose.yml -f docker-compose.prod.yml \\
        exec backend python scripts/diag_maybank.py

The output tells you exactly which path triggered and which decision to
take next (proceed / tune stealth / pay for unblock service / drop channel).
"""

from __future__ import annotations

import asyncio
import sys
import time
from decimal import Decimal

from app.scrapers.base import ScraperError
from app.scrapers.maybank import MaybankScraper, _PlaywrightUnavailable


async def _probe_playwright() -> None:
    """Verify Playwright + Chromium are usable in isolation."""
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        print(f"  [FAIL] playwright Python package not installed: {exc}")
        return

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            version = browser.version
            await browser.close()
        print(f"  [OK]   chromium launches; version = {version}")
    except Exception as exc:
        print(f"  [FAIL] chromium failed to launch: {type(exc).__name__}: {exc}")


async def _probe_scrape() -> int:
    """Run a real Maybank scrape. Return 0 on success, non-zero on failure."""
    scraper = MaybankScraper()
    t0 = time.time()
    try:
        result = await scraper.fetch("CNY", "MYR")
    except _PlaywrightUnavailable as exc:
        elapsed = time.time() - t0
        print(f"  [FAIL] PlaywrightUnavailable in {elapsed:.1f}s: {exc}")
        print("         → Chromium binary not in this image. Rebuild backend with")
        print("         → `playwright install --with-deps chromium` in the Dockerfile.")
        return 1
    except ScraperError as exc:
        elapsed = time.time() - t0
        msg = str(exc)
        print(f"  [FAIL] ScraperError in {elapsed:.1f}s: {msg}")
        if "did not appear" in msg or "challenge" in msg.lower():
            print("         → Akamai is serving an interstitial. Stealth tweaks")
            print("         → didn't fool it from this IP. Next step: try a paid")
            print("         → unblock service (ScrapingBee / ZenRows) or drop maybank.")
        elif "HTTP 403" in msg or "Akamai" in msg:
            print("         → Akamai blocked at HTTP layer (httpx fallback). Either")
            print("         → Playwright also failed earlier or it isn't running.")
        elif "navigation failed" in msg:
            print("         → Real network/TLS error reaching maybank2u.com.my.")
            print("         → Not a stealth problem — check OCI egress / DNS.")
        return 2
    except Exception as exc:
        elapsed = time.time() - t0
        print(f"  [FAIL] unexpected {type(exc).__name__} in {elapsed:.1f}s: {exc}")
        return 3

    elapsed = time.time() - t0
    in_range = Decimal("0.5") <= result.rate <= Decimal("0.8")
    print(f"  [OK]   scrape succeeded in {elapsed:.1f}s")
    print(f"         rate           = {result.rate} MYR per 1 CNY")
    print(f"         rate_type      = {result.rate_type}")
    print(f"         currency_label = {result.raw_payload.get('currency_label')!r}")
    print(f"         multiplier     = {result.raw_payload.get('multiplier')}")
    print(f"         tt_buying      = {result.raw_payload.get('tt_buying')!r}")
    print(f"         last_update    = {result.raw_payload.get('last_update')!r}")
    print(f"         in [0.5,0.8]   = {in_range}")
    return 0 if in_range else 4


async def _main() -> int:
    print("=== Maybank diagnostic ===")
    print("[1/2] Playwright / Chromium availability:")
    await _probe_playwright()
    print("[2/2] End-to-end scrape:")
    return await _probe_scrape()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
