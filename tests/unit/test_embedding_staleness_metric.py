"""Tests for embedding index staleness metric (Closes #1027).

Verifies kri_embedding_index_staleness_seconds is emitted correctly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch


class TestEmbeddingStalenessMetric:
    """Verify the embedding staleness gauge is populated correctly."""

    def test_gauge_is_defined(self):
        from fleet_platform.metrics import embedding_index_staleness_seconds

        assert embedding_index_staleness_seconds is not None
        assert embedding_index_staleness_seconds._name == "kri_embedding_index_staleness_seconds"

    @patch("fleet_platform.db.session.get_sync_db")
    def test_staleness_calculated_from_oldest_embedded_at(self, mock_get_db):
        from fleet_platform.api.metrics_collectors import refresh_embedding_staleness_gauge
        from fleet_platform.metrics import embedding_index_staleness_seconds

        # Mock DB returning oldest embedded_at as 2 hours ago
        oldest_time = datetime.now(UTC) - timedelta(hours=2)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = oldest_time
        mock_db = MagicMock()
        mock_db.execute.return_value = mock_result
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        refresh_embedding_staleness_gauge()

        # Should be approximately 7200 seconds (2 hours)
        value = embedding_index_staleness_seconds._value.get()
        assert 7100 < value < 7300, f"Expected ~7200s, got {value}"

    @patch("fleet_platform.db.session.get_sync_db")
    def test_staleness_zero_when_no_embeddings(self, mock_get_db):
        from fleet_platform.api.metrics_collectors import refresh_embedding_staleness_gauge
        from fleet_platform.metrics import embedding_index_staleness_seconds

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db = MagicMock()
        mock_db.execute.return_value = mock_result
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        refresh_embedding_staleness_gauge()

        value = embedding_index_staleness_seconds._value.get()
        assert value == 0.0

    @patch("fleet_platform.db.session.get_sync_db", side_effect=Exception("DB down"))
    def test_staleness_survives_db_error(self, mock_get_db):
        from fleet_platform.api.metrics_collectors import refresh_embedding_staleness_gauge

        # Should not raise
        refresh_embedding_staleness_gauge()
