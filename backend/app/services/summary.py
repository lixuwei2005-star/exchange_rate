"""AI summary regeneration.

Pulls the last 30 days of rate data, asks an OpenAI-compatible LLM for a
one-sentence Chinese trend summary, validates the output, persists it.

The provider is admin-configured at runtime (CLAUDE.md §10); we never import
the `anthropic` SDK and never hardcode a base_url.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models.ai_summary import AISummary
from app.models.rate_snapshot import RateSnapshot
from app.services.llm_client import get_client
from app.services.settings import get_setting

logger = logging.getLogger(__name__)

# Words that signal urgency / advice; output must NOT contain these.
URGENCY_WORDS = ("赶紧", "立刻", "立即", "马上", "尽快", "建议换汇", "建议立即")
EMOJI_PATTERN = re.compile("[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f100-\U0001f1ff]")
MAX_ZH_CHARS = 80


class SummaryValidationError(ValueError):
    pass


class BudgetExceededError(RuntimeError):
    pass


# --- in-memory daily budget tracker --------------------------------------


@dataclass
class _BudgetState:
    day: str = ""  # YYYY-MM-DD in SGT
    spent_usd: float = 0.0


_budget = _BudgetState()


def _sgt_today_iso() -> str:
    # Server tz is Singapore (CLAUDE.md). datetime.now() returns SGT.
    return datetime.now().strftime("%Y-%m-%d")


def _reset_budget_if_new_day() -> None:
    today = _sgt_today_iso()
    if _budget.day != today:
        _budget.day = today
        _budget.spent_usd = 0.0


def _estimate_cost(in_tokens: int, out_tokens: int, c_in_1k: float, c_out_1k: float) -> float:
    return (in_tokens / 1000.0) * c_in_1k + (out_tokens / 1000.0) * c_out_1k


# --- public API ----------------------------------------------------------


@dataclass
class _Stats:
    today_rate: Decimal
    pct_7d: Decimal
    pct_30d: Decimal
    high_30d: Decimal
    low_30d: Decimal


async def _collect_stats(session: AsyncSession, base: str, quote: str) -> _Stats | None:
    """Build the data block we hand to the LLM. Returns None if too sparse."""
    cutoff = datetime.now(UTC) - timedelta(days=30)
    q = (
        select(RateSnapshot)
        .where(
            RateSnapshot.channel_code.in_(["midmarket", "boc"]),
            RateSnapshot.base_currency == base,
            RateSnapshot.quote_currency == quote,
            RateSnapshot.fetched_at >= cutoff,
        )
        .order_by(RateSnapshot.fetched_at.desc())
    )
    rows = list((await session.execute(q)).scalars())
    if not rows:
        return None
    rates = [r.rate for r in rows]
    today_rate = rates[0]

    seven_cutoff = datetime.now(UTC) - timedelta(days=7)
    seven_rates = [
        r.rate
        for r in rows
        if (r.fetched_at.replace(tzinfo=UTC) if r.fetched_at.tzinfo is None else r.fetched_at)
        >= seven_cutoff
    ]
    base_for_pct_7 = seven_rates[-1] if seven_rates else today_rate
    base_for_pct_30 = rates[-1]

    def _pct(now: Decimal, then: Decimal) -> Decimal:
        if then == 0:
            return Decimal("0")
        return ((now - then) / then * Decimal("100")).quantize(Decimal("0.01"))

    return _Stats(
        today_rate=today_rate.quantize(Decimal("0.000001")),
        pct_7d=_pct(today_rate, base_for_pct_7),
        pct_30d=_pct(today_rate, base_for_pct_30),
        high_30d=max(rates),
        low_30d=min(rates),
    )


def _validate(text: str) -> None:
    if EMOJI_PATTERN.search(text):
        raise SummaryValidationError("contains emoji")
    for w in URGENCY_WORDS:
        if w in text:
            raise SummaryValidationError(f"contains urgency word: {w}")
    if len(text) > MAX_ZH_CHARS + 10:  # 10 char tolerance over the prompt cap
        raise SummaryValidationError(f"too long: {len(text)} chars")


async def regenerate(base: str = "CNY", quote: str = "MYR") -> AISummary | None:
    """Regenerate the latest AI summary. Returns the new row, or None on
    soft failure (no data / disabled / budget exceeded — logged)."""
    _reset_budget_if_new_day()
    async with SessionLocal() as session:
        if (await get_setting(session, "ai.enabled", "false")).lower() != "true":
            logger.info("ai.enabled is false; skipping summary regeneration")
            return None

        budget_str = await get_setting(session, "ai.daily_budget_usd", "0")
        try:
            budget = float(budget_str or "0")
        except ValueError:
            budget = 0.0
        if budget > 0 and _budget.spent_usd >= budget:
            logger.warning(
                "ai daily budget exceeded ($%.4f >= $%.4f); skipping", _budget.spent_usd, budget
            )
            return None

        stats = await _collect_stats(session, base, quote)
        if stats is None:
            logger.info("no rate data yet; skipping summary regeneration")
            return None

        system_prompt = await get_setting(session, "ai.system_prompt", "")
        model = await get_setting(session, "ai.model", "gpt-4o-mini")
        temperature = float(await get_setting(session, "ai.temperature", "0.2") or "0.2")
        max_tokens = int(await get_setting(session, "ai.max_tokens", "120") or "120")
        c_in_1k = float(await get_setting(session, "ai.cost_per_1k_input", "0") or "0")
        c_out_1k = float(await get_setting(session, "ai.cost_per_1k_output", "0") or "0")

        user_msg = (
            f"今日汇率：1 {base} = {stats.today_rate} {quote}\n"
            f"7日变化：{stats.pct_7d}%\n"
            f"30日变化：{stats.pct_30d}%\n"
            f"30日区间：{stats.low_30d} ~ {stats.high_30d}"
        )

        client = await get_client(session)
        text: str | None = None
        usage_in = 0
        usage_out = 0
        for attempt in range(2):  # one retry on validation failure
            try:
                resp = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                logger.exception("LLM call failed: %s", exc)
                return None
            choice = resp.choices[0] if resp.choices else None
            content = (choice.message.content if choice and choice.message else "") or ""
            content = content.strip()
            if resp.usage:
                usage_in += resp.usage.prompt_tokens or 0
                usage_out += resp.usage.completion_tokens or 0
            try:
                _validate(content)
            except SummaryValidationError as exc:
                logger.warning("summary validation failed (attempt %d): %s", attempt + 1, exc)
                continue
            text = content
            break

        # Budget bookkeeping happens whether we accept the text or not.
        _budget.spent_usd += _estimate_cost(usage_in, usage_out, c_in_1k, c_out_1k)

        if text is None:
            logger.warning("summary regeneration: no valid output; keeping previous")
            return None

        row = AISummary(
            base_currency=base,
            quote_currency=quote,
            summary_zh=text,
            model_used=model,
            generated_at=datetime.now(UTC),
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        logger.info("summary regenerated (model=%s, len=%d)", model, len(text))
        return row


async def get_today_budget_state() -> dict[str, float | str]:
    _reset_budget_if_new_day()
    return {"day": _budget.day, "spent_usd": _budget.spent_usd}
