"""Tests for rag_search chunk truncation limit (Closes #1026).

Verifies _rag_search returns up to 3000 chars per chunk (increased from 1500).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fleet_platform.agent import tools


class TestRagSearchTruncation:
    """Verify _rag_search returns up to 3000 chars per chunk."""

    def _make_ctx(self):
        return SimpleNamespace(db=SimpleNamespace())

    @patch("fleet_platform.services.embedding_svc.retrieve", new_callable=AsyncMock)
    @patch("fleet_platform.services.platform_settings_svc.get_setting", new_callable=AsyncMock)
    def test_long_chunk_truncated_at_3000(self, mock_get_setting, mock_retrieve):
        mock_get_setting.return_value = "http://embed:8080"
        long_text = "x" * 5000
        mock_retrieve.return_value = [{"source_type": "playbook", "source_id": "play:deploy", "chunk_text": long_text}]

        result = asyncio.run(tools._rag_search(self._make_ctx(), query="deploy nginx"))

        assert result["count"] == 1
        assert len(result["results"][0]["chunk_text"]) == 3000
        assert result["results"][0]["chunk_text"] == "x" * 3000

    @patch("fleet_platform.services.embedding_svc.retrieve", new_callable=AsyncMock)
    @patch("fleet_platform.services.platform_settings_svc.get_setting", new_callable=AsyncMock)
    def test_short_chunk_not_padded(self, mock_get_setting, mock_retrieve):
        mock_get_setting.return_value = "http://embed:8080"
        short_text = "hello world"
        mock_retrieve.return_value = [{"source_type": "node", "source_id": "node:web-1", "chunk_text": short_text}]

        result = asyncio.run(tools._rag_search(self._make_ctx(), query="web server status"))

        assert result["results"][0]["chunk_text"] == short_text

    @patch("fleet_platform.services.embedding_svc.retrieve", new_callable=AsyncMock)
    @patch("fleet_platform.services.platform_settings_svc.get_setting", new_callable=AsyncMock)
    def test_exactly_3000_chars_returned_in_full(self, mock_get_setting, mock_retrieve):
        mock_get_setting.return_value = "http://embed:8080"
        exact_text = "a" * 3000
        mock_retrieve.return_value = [
            {"source_type": "salt_state", "source_id": "states:base:pkg", "chunk_text": exact_text}
        ]

        result = asyncio.run(tools._rag_search(self._make_ctx(), query="salt state info"))

        assert len(result["results"][0]["chunk_text"]) == 3000

    @patch("fleet_platform.services.embedding_svc.retrieve", new_callable=AsyncMock)
    @patch("fleet_platform.services.platform_settings_svc.get_setting", new_callable=AsyncMock)
    def test_none_chunk_text_becomes_empty(self, mock_get_setting, mock_retrieve):
        mock_get_setting.return_value = "http://embed:8080"
        mock_retrieve.return_value = [{"source_type": "playbook", "source_id": "play:x", "chunk_text": None}]

        result = asyncio.run(tools._rag_search(self._make_ctx(), query="test"))

        assert result["results"][0]["chunk_text"] == ""
