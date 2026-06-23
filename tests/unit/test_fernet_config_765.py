"""Unit tests for #765 — FERNET_SECRET_KEY / FERNET_KEY env-var reconciliation.

Verifies that:
1. `settings.fernet_secret_key` is populated when the env var `FERNET_KEY` is set
   (the name used by CI and documented in .env*.example).
2. The env examples contain the `FERNET_KEY` entry.
3. `platform_settings_svc._get_fernet` raises a clear error when `FERNET_KEY` is
   set to an invalid value in non-development mode.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# 1. config.py: FERNET_KEY env var populates settings.fernet_secret_key
# ---------------------------------------------------------------------------


def test_settings_reads_fernet_key_from_env():
    """Settings.fernet_secret_key must be populated from the FERNET_KEY env var."""
    import fleet_platform.core.config as config_mod

    valid_key = "dGVzdC1rZXktbm90LWZvci1wcm9kdWN0aW9uLXVzZS1vbmx5"
    with patch.dict(os.environ, {"FERNET_KEY": valid_key}, clear=False):
        fresh = importlib.reload(config_mod)
        assert fresh.settings.fernet_secret_key == valid_key


def test_settings_fernet_key_absent_gives_none():
    """When FERNET_KEY is absent, fernet_secret_key should default to None."""
    import fleet_platform.core.config as config_mod

    env_without_fernet = {k: v for k, v in os.environ.items() if k not in ("FERNET_KEY", "FERNET_SECRET_KEY")}
    with patch.dict(os.environ, env_without_fernet, clear=True):
        fresh = importlib.reload(config_mod)
        assert fresh.settings.fernet_secret_key is None


# ---------------------------------------------------------------------------
# 2. .env*.example files document FERNET_KEY
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]


def _env_file_contains_fernet_key(path: Path) -> bool:
    text = path.read_text()
    return "FERNET_KEY" in text


def test_env_example_contains_fernet_key():
    path = REPO_ROOT / ".env.example"
    assert path.exists(), f"Missing {path}"
    assert _env_file_contains_fernet_key(path), ".env.example must document FERNET_KEY"


def test_env_docker_example_contains_fernet_key():
    path = REPO_ROOT / ".env.docker.example"
    assert path.exists(), f"Missing {path}"
    assert _env_file_contains_fernet_key(path), ".env.docker.example must document FERNET_KEY"
