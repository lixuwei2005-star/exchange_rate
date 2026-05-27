"""Shared helpers for scrapers."""

from __future__ import annotations

from decimal import Decimal

import httpx

UA = "rate.005917.xyz contact: lixuwei2005@gmail.com"


def make_client(timeout: int = 15) -> httpx.AsyncClient:
    """Async HTTP client with our UA and reasonable defaults."""
    return httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": UA, "Accept-Language": "zh-CN,en;q=0.8"},
        follow_redirects=True,
    )


def to_decimal(value: object) -> Decimal:
    """Tolerant Decimal conversion: strips commas, accepts str/int/float."""
    if value is None:
        raise ValueError("rate is None")
    s = str(value).replace(",", "").strip()
    if not s:
        raise ValueError("rate is empty string")
    return Decimal(s)
