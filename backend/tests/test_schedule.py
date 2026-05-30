"""Per-channel schedule: trigger selection + weekdays validation.

Covers app.scheduler._trigger_for (interval / daily / weekly + fallbacks) and
the ChannelPatch.weekdays normalization in app.schemas.admin.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from pydantic import ValidationError

from app.models.channel import Channel
from app.scheduler import DEFAULT_INTERVAL_MINUTES, _trigger_for
from app.schemas.admin import ChannelPatch


def _ch(**kw: object) -> Channel:
    base: dict[str, object] = {
        "code": "x",
        "name_en": "X",
        "name_zh": "测试",
        "schedule_kind": "interval",
        "interval_minutes": None,
        "daily_time_cn": None,
        "weekdays": None,
    }
    base.update(kw)
    return Channel(**base)


def _fields(trigger: CronTrigger) -> dict[str, str]:
    return {f.name: str(f) for f in trigger.fields}


# ---- _trigger_for: interval -------------------------------------------


def test_interval_trigger():
    t = _trigger_for(_ch(schedule_kind="interval", interval_minutes=15))
    assert isinstance(t, IntervalTrigger)
    assert t.interval == timedelta(minutes=15)


def test_interval_missing_minutes_falls_back_to_default():
    t = _trigger_for(_ch(schedule_kind="interval", interval_minutes=None))
    assert isinstance(t, IntervalTrigger)
    assert t.interval == timedelta(minutes=DEFAULT_INTERVAL_MINUTES)


# ---- _trigger_for: daily ----------------------------------------------


def test_daily_trigger_every_day():
    t = _trigger_for(_ch(schedule_kind="daily", daily_time_cn="11:30"))
    assert isinstance(t, CronTrigger)
    f = _fields(t)
    assert f["hour"] == "11"
    assert f["minute"] == "30"
    assert f["day_of_week"] == "*"  # every day
    assert str(t.timezone) == "Asia/Shanghai"


def test_daily_bad_time_falls_back_to_interval():
    t = _trigger_for(_ch(schedule_kind="daily", daily_time_cn="9am", interval_minutes=20))
    assert isinstance(t, IntervalTrigger)
    assert t.interval == timedelta(minutes=20)


# ---- _trigger_for: weekly ---------------------------------------------


def test_weekly_trigger_selected_days():
    t = _trigger_for(
        _ch(schedule_kind="weekly", daily_time_cn="18:00", weekdays="mon,tue,wed,thu,fri")
    )
    assert isinstance(t, CronTrigger)
    f = _fields(t)
    assert f["hour"] == "18"
    assert f["minute"] == "0"
    dow = f["day_of_week"]
    for tok in ("mon", "tue", "wed", "thu", "fri"):
        assert tok in dow
    assert "sat" not in dow and "sun" not in dow
    assert str(t.timezone) == "Asia/Shanghai"


def test_weekly_without_weekdays_falls_back_to_interval():
    t = _trigger_for(
        _ch(schedule_kind="weekly", daily_time_cn="18:00", weekdays=None, interval_minutes=45)
    )
    assert isinstance(t, IntervalTrigger)
    assert t.interval == timedelta(minutes=45)


def test_weekly_bad_time_falls_back_to_interval():
    t = _trigger_for(_ch(schedule_kind="weekly", daily_time_cn="25:99", weekdays="sat,sun"))
    assert isinstance(t, IntervalTrigger)
    assert t.interval == timedelta(minutes=DEFAULT_INTERVAL_MINUTES)


# ---- ChannelPatch.weekdays validation ---------------------------------


def test_patch_accepts_weekly_kind():
    assert ChannelPatch(schedule_kind="weekly").schedule_kind == "weekly"


def test_patch_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        ChannelPatch(schedule_kind="monthly")


def test_patch_weekdays_normalized_to_canonical_order():
    assert ChannelPatch(weekdays="fri,mon,wed").weekdays == "mon,wed,fri"


def test_patch_weekdays_dedup_and_case_insensitive():
    assert ChannelPatch(weekdays="MON, mon ,Tue").weekdays == "mon,tue"


def test_patch_weekdays_rejects_invalid_token():
    with pytest.raises(ValidationError):
        ChannelPatch(weekdays="mon,funday")


def test_patch_weekdays_rejects_empty():
    with pytest.raises(ValidationError):
        ChannelPatch(weekdays=" , ")
