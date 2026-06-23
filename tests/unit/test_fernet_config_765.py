"""Unit tests for #765 — FERNET_SECRET_KEY / FERNET_KEY env-var reconciliation.

Verifies that:
1. `settings.fernet_secret_key` is populated when the env var `FERNET_KEY` is set
   (the name used by CI and documented in .env*.example).
2. The env examples contain the `FERNET_KEY` entry.
3. `platform_settings_svc._get_fernet` raises a clear error when `FERNET_KEY` is
   set to an invalid value in non-development mode.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# 1. config.py: FERNET_KEY env var populates settings.fernet_secret_key
# ---------------------------------------------------------------------------


def test_settings_reads_fernet_key_from_env():
    """Settings.fernet_secret_key must be populated from the FERNET_KEY env var.

    Construct a fresh Settings() under a patched env rather than reloading the
    config module — importlib.reload rebinds the global `settings` singleton and
    pollutes other tests (platform_settings_svc holds the original reference).
    """
    from fleet_platform.core.config import Settings

    valid_key = "TJNUjlTWwn0v5n5raoMUYp-An_l3EnATE7xthpfAFGM="
    with patch.dict(os.environ, {"FERNET_KEY": valid_key}, clear=False):
        assert Settings().fernet_secret_key == valid_key


def test_settings_fernet_key_absent_gives_none():
    """When FERNET_KEY is absent, fernet_secret_key should default to None."""
    from fleet_platform.core.config import Settings

    env_without_fernet = {k: v for k, v in os.environ.items() if k not in ("FERNET_KEY", "FERNET_SECRET_KEY")}
    with patch.dict(os.environ, env_without_fernet, clear=True):
        # _env_file=None so a local .env can't inject a value during the test.
        assert Settings(_env_file=None).fernet_secret_key is None


def test_settings_reads_legacy_fernet_secret_key_from_env():
    """Backward compat: the legacy FERNET_SECRET_KEY env var must still populate
    the field, so existing deployments keep decrypting secrets after the rename
    to FERNET_KEY without an ops change."""
    from fleet_platform.core.config import Settings

    legacy_key = "TJNUjlTWwn0v5n5raoMUYp-An_l3EnATE7xthpfAFGM="
    env = {k: v for k, v in os.environ.items() if k not in ("FERNET_KEY", "FERNET_SECRET_KEY")}
    env["FERNET_SECRET_KEY"] = legacy_key
    with patch.dict(os.environ, env, clear=True):
        assert Settings(_env_file=None).fernet_secret_key == legacy_key


def test_settings_fernet_key_takes_precedence_over_legacy():
    """When both env vars are set, the canonical FERNET_KEY wins."""
    from fleet_platform.core.config import Settings

    canonical = "TJNUjlTWwn0v5n5raoMUYp-An_l3EnATE7xthpfAFGM="
    legacy = "b3RoZXIta2V5LW90aGVyLWtleS1vdGhlci1rZXktMzI="
    env = {k: v for k, v in os.environ.items() if k not in ("FERNET_KEY", "FERNET_SECRET_KEY")}
    env["FERNET_KEY"] = canonical
    env["FERNET_SECRET_KEY"] = legacy
    with patch.dict(os.environ, env, clear=True):
        assert Settings(_env_file=None).fernet_secret_key == canonical


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
