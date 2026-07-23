"""Tests for salt state reindexing Celery task (Closes #1024).

Verifies reindex_salt_states reads .sls files, chunks them, and upserts.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


class TestReindexSaltStates:
    """Verify the reindex_salt_states Celery task."""

    @patch("fleet_platform.services.embedding_svc.upsert_chunks", new_callable=AsyncMock)
    @patch("fleet_platform.services.embedding_svc.sweep_deleted_sources", new_callable=AsyncMock)
    @patch("fleet_platform.services.platform_settings_svc.get_settings_bulk", new_callable=AsyncMock)
    def test_upserts_salt_state_chunks(self, mock_settings, mock_sweep, mock_upsert):
        mock_settings.return_value = {
            "llm_embed_base_url": "http://embed:8080",
            "SALT_STATES_DIR": "/srv/salt/states",
        }
        mock_upsert.return_value = 3
        mock_sweep.return_value = 0

        sls_content = """
deploy_nginx:
  pkg.installed:
    - name: nginx

nginx_service:
  service.running:
    - name: nginx
    - enable: True
"""
        mock_sls_file = MagicMock(spec=Path)
        mock_sls_file.read_text.return_value = sls_content
        mock_sls_file.relative_to.return_value = "base/deploy.sls"

        with (
            patch("fleet_platform.workers.embedding_tasks.Path") as MockPath,
            patch("fleet_platform.services.embedding_svc.chunk_salt_state") as mock_chunk,
        ):
            MockPath.return_value.glob.return_value = [mock_sls_file]
            mock_chunk.return_value = [
                {"source_type": "salt_state", "source_id": "deploy:deploy_nginx", "chunk_text": "chunk1"},
                {"source_type": "salt_state", "source_id": "deploy:nginx_service", "chunk_text": "chunk2"},
            ]

            from fleet_platform.workers.embedding_tasks import reindex_salt_states

            result = reindex_salt_states()

        assert result["upserted"] == 3
        assert result["total"] == 2
        mock_chunk.assert_called_once_with("salt/states/base/deploy.sls", sls_content)
        mock_sweep.assert_called_once()

    @patch("fleet_platform.services.platform_settings_svc.get_settings_bulk", new_callable=AsyncMock)
    def test_skips_when_no_embed_url(self, mock_settings):
        mock_settings.return_value = {"llm_embed_base_url": ""}

        from fleet_platform.workers.embedding_tasks import reindex_salt_states

        result = reindex_salt_states()
        assert "skipped" in result

    @patch("fleet_platform.services.platform_settings_svc.get_settings_bulk", new_callable=AsyncMock)
    def test_skips_when_no_states_dir(self, mock_settings):
        mock_settings.return_value = {
            "llm_embed_base_url": "http://embed:8080",
            "SALT_STATES_DIR": "",
        }

        from fleet_platform.workers.embedding_tasks import reindex_salt_states

        result = reindex_salt_states()
        assert "skipped" in result

    def test_task_name_is_correct(self):
        from fleet_platform.workers.embedding_tasks import reindex_salt_states

        assert reindex_salt_states.name == "fleet_platform.workers.embedding_tasks.reindex_salt_states"
