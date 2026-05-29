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
from app.models.channel import Channel
from app.models.rate_snapshot import RateSnapshot
from app.services.llm_client import get_client
from app.services.rates import as_utc, headline_rate_for
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
class _ChannelStat:
    name_zh: str
    code: str
    today: Decimal  # display value: 1 MYR = X CNY (= 1 / headline rate)
    pct_7d: Decimal | None  # change of the display value over ~7 days
    pct_30d: Decimal | None


@dataclass
class _Stats:
    channels: list[_ChannelStat]  # active providers, best (lowest display) first
    ref_name: str  # reference channel for the trend line (deepest history)
    ref_today: Decimal
    ref_pct_7d: Decimal
    ref_pct_30d: Decimal
    ref_low_30d: Decimal  # display
    ref_high_30d: Decimal  # display


def _pct(now: Decimal, then: Decimal) -> Decimal:
    if then == 0:
        return Decimal("0")
    return ((now - then) / then * Decimal("100")).quantize(Decimal("0.01"))


def _display(snap: RateSnapshot) -> Decimal | None:
    """1 MYR = X CNY — the value shown on the site (= 1 / headline rate)."""
    h = headline_rate_for(snap)
    if h <= 0:
        return None
    return (Decimal("1") / h).quantize(Decimal("0.0001"))


async def _collect_stats(session: AsyncSession, base: str, quote: str) -> _Stats | None:
    """Build the data block we hand to the LLM.

    Covers every ACTIVE provider's current rate (as 1 MYR = X CNY) plus its
    7-/30-day change, and a reference trend taken from the channel with the
    deepest history (so the 7-/30-day figures are meaningful even while most
    bank channels have only days of data). Returns None if too sparse.
    """
    now = datetime.now(UTC)
    cutoff_30 = now - timedelta(days=30)
    cutoff_7 = now - timedelta(days=7)

    channels = list(
        (await session.execute(select(Channel).where(Channel.active.is_(True)))).scalars()
    )
    if not channels:
        return None

    per_channel: list[_ChannelStat] = []
    ref: _Stats | None = None
    ref_points = -1

    for ch in channels:
        rows = list(
            (
                await session.execute(
                    select(RateSnapshot)
                    .where(
                        RateSnapshot.channel_code == ch.code,
                        RateSnapshot.base_currency == base,
                        RateSnapshot.quote_currency == quote,
                        RateSnapshot.fetched_at >= cutoff_30,
                    )
                    .order_by(RateSnapshot.fetched_at)
                )
            ).scalars()
        )
        series = [(as_utc(s.fetched_at), _display(s)) for s in rows]
        series = [(t, d) for t, d in series if d is not None]
        if not series:
            continue

        today = series[-1][1]
        base_30 = series[0][1]
        within_7 = [d for t, d in series if t >= cutoff_7]
        base_7 = within_7[0] if within_7 else None
        multi = len(series) > 1
        pct_7 = _pct(today, base_7) if (multi and base_7 is not None) else None
        pct_30 = _pct(today, base_30) if (multi and base_30 is not None) else None
        per_channel.append(_ChannelStat(ch.name_zh, ch.code, today, pct_7, pct_30))

        if len(series) > ref_points:
            ref_points = len(series)
            disp = [d for _, d in series]
            ref = _Stats(
                channels=[],  # filled in after the loop
                ref_name=ch.name_zh,
                ref_today=today,
                ref_pct_7d=pct_7 if pct_7 is not None else Decimal("0"),
                ref_pct_30d=pct_30 if pct_30 is not None else Decimal("0"),
                ref_low_30d=min(disp),
                ref_high_30d=max(disp),
            )

    if not per_channel or ref is None:
        return None
    # Lowest "1 MYR = X CNY" first == most MYR per CNY == best for the customer.
    per_channel.sort(key=lambda c: c.today)
    ref.channels = per_channel
    return ref


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

        lines = ["今日各渠道汇率（1 MYR = X CNY，数值越低越划算）："]
        for c in stats.channels:
            if c.pct_7d is not None and c.pct_30d is not None:
                trend = f"（7日 {c.pct_7d:+}%，30日 {c.pct_30d:+}%）"
            else:
                trend = "（暂无历史）"
            lines.append(f"- {c.name_zh}：{c.today} {trend}")
        lines.append("")
        lines.append(
            f"参考走势（{stats.ref_name}）：今日 1 {quote} = {stats.ref_today} {base}，"
            f"7日变化 {stats.ref_pct_7d:+}%，30日变化 {stats.ref_pct_30d:+}%，"
            f"30日区间 {stats.ref_low_30d} ~ {stats.ref_high_30d}。"
        )
        lines.append(
            "注：上述「1 MYR = X CNY」数值下降代表人民币升值（同样人民币能换更多马币），"
            "上升代表贬值。"
        )
        lines.append(
            "请用一句话（不超过 80 字）总结：今日哪个渠道最划算、与中间市场的差距、"
            "以及近 7 日 / 30 日趋势；只陈述事实，不要催促换汇。"
        )
        user_msg = "\n".join(lines)

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
