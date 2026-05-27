from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.models.ai_summary import AISummary
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
async def test_regenerate_writes_summary_when_enabled(session):
    # arrange: enable AI, configure provider, seed a snapshot
    await set_setting(session, "ai.enabled", "true")
    await set_setting(session, "ai.base_url", "https://fake/v1")
    await set_setting(session, "ai.api_key", "sk-fake")
    await set_setting(session, "ai.model", "fake-model")
    await session.commit()

    session.add(
        RateSnapshot(
            channel_code="midmarket",
            base_currency="CNY",
            quote_currency="MYR",
            rate=Decimal("0.65"),
            rate_type="midmarket",
            raw_payload={},
            fetched_at=datetime.now(UTC) - timedelta(days=1),
        )
    )
    await session.commit()

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=AsyncMock(return_value=_fake_completion("今日小幅上行，整体平稳。"))
            )
        )
    )
    with patch("app.services.summary.get_client", AsyncMock(return_value=fake_client)):
        row = await regenerate("CNY", "MYR")
    assert row is not None
    assert isinstance(row, AISummary)
    assert row.model_used == "fake-model"
    assert "上行" in row.summary_zh


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
