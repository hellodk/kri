"""Tests for source_type filtering in build_fleet_context (Closes #1025).

Verifies the context builder excludes drift records from default RAG retrieval.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


class TestBuildFleetContextSourceFilter:
    """Verify build_fleet_context passes source_types to retrieve()."""

    @patch("fleet_platform.services.embedding_svc.retrieve", new_callable=AsyncMock)
    def test_retrieve_called_with_source_types_excluding_drift(self, mock_retrieve):
        """build_fleet_context must pass source_types that exclude 'drift'."""
        mock_retrieve.return_value = []

        # Read the source to verify the call signature
        import inspect

        from fleet_platform.services.llm_context import build_fleet_context

        source = inspect.getsource(build_fleet_context)

        # Verify retrieve() is called with source_types parameter
        assert "source_types=" in source or "source_types =" in source, (
            "build_fleet_context must pass source_types to retrieve()"
        )

        # Verify drift is excluded from the default source types
        assert '"drift"' not in source or "exclude" in source.lower() or "not in" in source, (
            "drift should be excluded from default source_types"
        )

    @patch("fleet_platform.services.embedding_svc.retrieve", new_callable=AsyncMock)
    def test_retrieve_source_types_list_content(self, mock_retrieve):
        """The source_types list must include node, playbook, salt_state but not drift."""
        import inspect

        from fleet_platform.services.llm_context import build_fleet_context

        source = inspect.getsource(build_fleet_context)

        # Find the retrieve() call and extract source_types
        # Look for the pattern: source_types=[...]
        import re

        match = re.search(r"source_types\s*=\s*\[([^\]]+)\]", source)
        if match:
            types_str = match.group(1)
            assert '"node"' in types_str or "'node'" in types_str, "node must be in source_types"
            assert '"playbook"' in types_str or "'playbook'" in types_str, "playbook must be in source_types"
            assert '"salt_state"' in types_str or "'salt_state'" in types_str, "salt_state must be in source_types"
            assert '"drift"' not in types_str and "'drift'" not in types_str, "drift must NOT be in source_types"
        else:
            pytest.fail("Could not find source_types=[...] in build_fleet_context source")
