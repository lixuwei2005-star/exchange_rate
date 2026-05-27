"""Fee constants and conversion math (CLAUDE.md §6).

Single source of truth for per-channel fees. Frontend mirrors these so the
homepage's '你能拿到' column matches what the backend would compute.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

# Fee constants per channel. Source: CLAUDE.md §6.
# All verified 2026-05-27. Bump # TODO recheck-YYYY-MM when you confirm.

BOC_TT_FEE_CNY: Decimal = Decimal("50")  # BOC TT outbound flat fee  # TODO recheck-2026-11
UNIONPAY_MARKUP: Decimal = Decimal("0")  # Markup baked into UnionPay's quote.
VISA_ISSUER_MARKUP: Decimal = Decimal("0.02")  # ~2% conservative  # TODO recheck-2026-11
MASTERCARD_ISSUER_MARKUP: Decimal = Decimal("0.02")  # TODO recheck-2026-11
WISE_FEE_DYNAMIC: bool = True  # Wise API returns explicit fee per quote
MAYBANK_TT_FEE_MYR: Decimal = Decimal("10")  # approximate  # TODO recheck-2026-11
CIMB_TT_FEE_MYR: Decimal = Decimal("10")  # approximate  # TODO recheck-2026-11


FeeKind = Literal["flat_cny", "flat_myr", "none"]


@dataclass(frozen=True)
class Fee:
    kind: FeeKind
    amount: Decimal


FEES: dict[str, Fee] = {
    "boc": Fee("flat_cny", BOC_TT_FEE_CNY),
    "maybank": Fee("flat_myr", MAYBANK_TT_FEE_MYR),
    "cimb": Fee("flat_myr", CIMB_TT_FEE_MYR),
    # Visa/MC markup is already baked into the stored rate (the scraper
    # multiplied by 1 - markup). UnionPay quote already includes its markup.
    # Wise is dynamic per-quote so we don't precompute. Midmarket has no fee.
}


def fee_for(channel: str) -> Fee:
    return FEES.get(channel, Fee("none", Decimal("0")))


def apply_fees(channel: str, cny_amount: Decimal, myr_per_cny: Decimal) -> Decimal:
    """Convert N CNY to MYR for the given channel, applying its modeled fee.

    `myr_per_cny` is the stored snapshot rate. Returns Decimal MYR amount
    (>= 0). Frontend mirrors this in lib/format.ts::convertCnyToMyr."""
    if cny_amount <= 0 or myr_per_cny <= 0:
        return Decimal("0")
    f = fee_for(channel)
    cny = cny_amount
    myr_fee = Decimal("0")
    if f.kind == "flat_cny":
        cny = max(Decimal("0"), cny_amount - f.amount)
    elif f.kind == "flat_myr":
        myr_fee = f.amount
    gross = cny * myr_per_cny
    net = gross - myr_fee
    return net if net > 0 else Decimal("0")
