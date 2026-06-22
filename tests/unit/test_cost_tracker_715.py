"""Unit tests for cloud cost tracking + daily cap (#715)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from fleet_platform.services import cost_tracker
from fleet_platform.services.cost_tracker import _CostState


@pytest.fixture(autouse=True)
def _reset():
    cost_tracker.STATE.reset()
    yield
    cost_tracker.STATE.reset()


def test_starts_at_zero_and_can_spend():
    assert cost_tracker.STATE.today_spend() == 0.0
    assert cost_tracker.can_spend() is True


def test_recording_tokens_accumulates():
    c1 = cost_tracker.record_tokens(1000, 1000)
    assert c1 > 0
    assert cost_tracker.STATE.today_spend() == pytest.approx(c1)
    cost_tracker.record_tokens(1000, 0)
    assert cost_tracker.STATE.today_spend() > c1


def test_daily_cap_blocks_spend():
    st = _CostState()
    today = date(2026, 6, 22)
    # Spend enough to blow the cap.
    huge_tokens = int(cost_tracker.DAILY_CAP_USD / cost_tracker.COST_PER_1K_TOKENS_USD * 1000) + 5000
    st.record_tokens(huge_tokens, 0, today=today)
    assert st.can_spend(today=today) is False
    assert st.snapshot(today=today)["capped"] is True


def test_spend_rolls_over_at_midnight():
    st = _CostState()
    d1 = date(2026, 6, 22)
    d2 = d1 + timedelta(days=1)
    st.record_tokens(1_000_000, 0, today=d1)
    assert st.today_spend(today=d1) > 0
    # New day resets the accumulator.
    assert st.today_spend(today=d2) == 0.0
    assert st.can_spend(today=d2) is True


def test_snapshot_shape():
    snap = cost_tracker.snapshot()
    assert set(snap) == {"date", "spend_usd", "daily_cap_usd", "remaining_usd", "capped"}
    assert snap["remaining_usd"] == pytest.approx(snap["daily_cap_usd"])
