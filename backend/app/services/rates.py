"""Small shared helpers for working with rate snapshots.

Extracted so both the public API and the AI-summary service can share the
headline-rate logic without the service layer importing from the API layer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.models.rate_snapshot import RateSnapshot


def as_utc(dt: datetime) -> datetime:
    """SQLite drops tz info — treat naive datetimes from the DB as UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def headline_rate_for(snap: RateSnapshot) -> Decimal:
    """Pre-fee advertised rate (quote per 1 base) for a snapshot.

    For most channels the stored rate IS the headline (bank ask, card-network
    rate, mid-market reference). Wise is the exception: we store the after-fee
    effective rate, but its advertised rate is the mid-market value embedded in
    the quote response — pull it from raw_payload so comparisons stay honest.
    """
    if snap.channel_code != "wise":
        return snap.rate
    raw = snap.raw_payload if isinstance(snap.raw_payload, dict) else {}
    direct = raw.get("rate")
    if direct is not None:
        try:
            return Decimal(str(direct))
        except Exception:
            pass
    # reverse_pair fallback shape: raw_payload = {"reverse_payload": {"rate": ...}}
    rev = raw.get("reverse_payload")
    if isinstance(rev, dict) and rev.get("rate") is not None:
        try:
            return (Decimal("1") / Decimal(str(rev["rate"]))).quantize(Decimal("0.00000001"))
        except Exception:
            pass
    return snap.rate
