"""Tests for Redis-backed cost cap sharing across workers (Closes #1030).

Verifies can_spend() and record_tokens() use Redis when available, with
fallback to local state when Redis is unavailable.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestCostTrackerRedis:
    """Verify Redis-backed cost tracking."""

    @patch("fleet_platform.services.cost_tracker._get_redis")
    def test_can_spend_uses_redis(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_redis.get.return_value = b"2.5"  # $2.50 spent today
        mock_get_redis.return_value = mock_redis

        from fleet_platform.services.cost_tracker import can_spend

        result = can_spend()
        assert result is True  # $2.50 < $5.00 cap

    @patch("fleet_platform.services.cost_tracker._get_redis")
    def test_can_spend_false_when_over_cap(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_redis.get.return_value = b"5.5"  # $5.50 spent > $5.00 cap
        mock_get_redis.return_value = mock_redis

        from fleet_platform.services.cost_tracker import can_spend

        result = can_spend()
        assert result is False

    @patch("fleet_platform.services.cost_tracker._get_redis")
    def test_record_tokens_increments_redis(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_redis.incrbyfloat.return_value = 3.0
        mock_get_redis.return_value = mock_redis

        from fleet_platform.services.cost_tracker import record_tokens

        cost = record_tokens(1000, 500)  # 1500 tokens * $0.009/1K = $0.0135
        assert cost > 0
        mock_redis.incrbyfloat.assert_called_once()

    @patch("fleet_platform.services.cost_tracker._get_redis", return_value=None)
    def test_falls_back_to_local_state(self, mock_get_redis):
        from fleet_platform.services.cost_tracker import can_spend, record_tokens

        # Should work with local state when Redis is unavailable
        cost = record_tokens(1000, 500)
        assert cost > 0
        result = can_spend()
        assert isinstance(result, bool)

    @patch("fleet_platform.services.cost_tracker._get_redis")
    def test_redis_key_has_ttl(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_redis.incrbyfloat.return_value = 1.0
        mock_get_redis.return_value = mock_redis

        from fleet_platform.services.cost_tracker import record_tokens

        record_tokens(1000, 500)
        # Verify expire was called with 48h TTL
        mock_redis.expire.assert_called()

    @patch("fleet_platform.services.cost_tracker._get_redis")
    def test_snapshot_reads_from_redis(self, mock_get_redis):
        mock_redis = MagicMock()
        mock_redis.get.return_value = b"3.14"
        mock_get_redis.return_value = mock_redis

        from fleet_platform.services.cost_tracker import snapshot

        result = snapshot()
        assert result["spend_usd"] == 3.14
        assert result["daily_cap_usd"] == 5.0
        assert result["remaining_usd"] == round(5.0 - 3.14, 4)
