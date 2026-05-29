from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.models.ai_summary import AISummary
from app.models.channel import Channel
from app.models.rate_snapshot import RateSnapshot
from app.services.settings import set_setting
from app.services.summary import (
    MAX_ZH_CHARS,
    SummaryValidationError,
    _validate,
    regenerate,
)


def test_validate_accepts_clean_chinese():
    _validate("今日人民币兑马币小幅上行，30日波动有限。")


def test_validate_rejects_urgency():
    with pytest.raises(SummaryValidationError):
        _validate("人民币上行，建议立即换汇。")


def test_validate_rejects_emoji():
    with pytest.raises(SummaryValidationError):
        _validate("今日人民币上行 📈")


def test_validate_rejects_too_long():
    too_long = "今" * (MAX_ZH_CHARS + 50)
    with pytest.raises(SummaryValidationError):
        _validate(too_long)


def _fake_completion(text: str, model: str = "fake-model"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20),
        model=model,
    )


@pytest.mark.asyncio
async def test_regenerate_writes_summary_and_prompt_covers_active_providers(session):
    # arrange: enable AI, configure provider
    await set_setting(session, "ai.enabled", "true")
    await set_setting(session, "ai.base_url", "https://fake/v1")
    await set_setting(session, "ai.api_key", "sk-fake")
    await set_setting(session, "ai.model", "fake-model")
    await session.commit()

    # two active providers + one inactive one (must be excluded)
    session.add_all(
        [
            Channel(code="midmarket", name_en="Mid", name_zh="中间市场汇率 1", active=True),
            Channel(code="wise", name_en="Wise", name_zh="Wise", active=True),
            Channel(code="off", name_en="Off", name_zh="停用渠道", active=False),
        ]
    )
    now = datetime.now(UTC)
    session.add_all(
        [
            RateSnapshot(
                channel_code="midmarket",
                base_currency="CNY",
                quote_currency="MYR",
                rate=Decimal("0.5800"),
                rate_type="midmarket",
                raw_payload={},
                fetched_at=now - timedelta(days=20),
            ),
            RateSnapshot(
                channel_code="midmarket",
                base_currency="CNY",
                quote_currency="MYR",
                rate=Decimal("0.5830"),
                rate_type="midmarket",
                raw_payload={},
                fetched_at=now - timedelta(hours=1),
            ),
            # Wise stores the after-fee rate; the headline is raw_payload["rate"].
            RateSnapshot(
                channel_code="wise",
                base_currency="CNY",
                quote_currency="MYR",
                rate=Decimal("0.5750"),
                rate_type="p2p",
                raw_payload={"rate": 0.5850},
                fetched_at=now - timedelta(hours=1),
            ),
            # Inactive channel — its snapshot must NOT reach the prompt.
            RateSnapshot(
                channel_code="off",
                base_currency="CNY",
                quote_currency="MYR",
                rate=Decimal("0.5000"),
                rate_type="midmarket",
                raw_payload={},
                fetched_at=now - timedelta(hours=1),
            ),
        ]
    )
    await session.commit()

    create = AsyncMock(
        return_value=_fake_completion("今日 Wise 最划算，1 MYR≈1.71 CNY，近30日小幅波动。")
    )
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with patch("app.services.summary.get_client", AsyncMock(return_value=fake_client)):
        row = await regenerate("CNY", "MYR")

    assert row is not None
    assert isinstance(row, AISummary)
    assert row.model_used == "fake-model"

    # The prompt now covers every active provider + the comparison instruction.
    _, kwargs = create.call_args
    user_msg = kwargs["messages"][1]["content"]
    assert "中间市场汇率 1" in user_msg
    assert "Wise" in user_msg
    assert "停用渠道" not in user_msg  # inactive provider excluded
    assert "1 MYR = X CNY" in user_msg  # display convention stated
    assert "渠道" in user_msg  # instruction to compare channels


@pytest.mark.asyncio
async def test_regenerate_skips_when_ai_disabled(session):
    await set_setting(session, "ai.enabled", "false")
    await session.commit()
    row = await regenerate("CNY", "MYR")
    assert row is None


@pytest.mark.asyncio
async def test_regenerate_skips_when_no_rate_data(session):
    await set_setting(session, "ai.enabled", "true")
    await set_setting(session, "ai.base_url", "https://fake/v1")
    await set_setting(session, "ai.api_key", "sk-fake")
    await session.commit()
    row = await regenerate("CNY", "MYR")
    assert row is None
