"""
tests/unit/test_standalone_systemd_431.py

Validates that the standalone systemd deploy artefacts (issue #431) are
present, structurally correct, and free of embedded secrets.

All tests are pure filesystem reads — no network, no DB, no imports of
application code.
"""

from __future__ import annotations

import re
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[2]
SYSTEMD_DIR = REPO_ROOT / "deploy" / "systemd"

API_UNIT = SYSTEMD_DIR / "kri-api.service"
WORKER_UNIT = SYSTEMD_DIR / "kri-worker.service"
BEAT_UNIT = SYSTEMD_DIR / "kri-beat.service"
ENV_EXAMPLE = SYSTEMD_DIR / "kri.env.example"
README = SYSTEMD_DIR / "README.md"

ALL_UNITS = [API_UNIT, WORKER_UNIT, BEAT_UNIT]

# ── Helpers ────────────────────────────────────────────────────────────────────


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── Existence tests ────────────────────────────────────────────────────────────


def test_api_service_exists() -> None:
    assert API_UNIT.exists(), f"Missing: {API_UNIT}"


def test_worker_service_exists() -> None:
    assert WORKER_UNIT.exists(), f"Missing: {WORKER_UNIT}"


def test_beat_service_exists() -> None:
    assert BEAT_UNIT.exists(), f"Missing: {BEAT_UNIT}"


def test_env_example_exists() -> None:
    assert ENV_EXAMPLE.exists(), f"Missing: {ENV_EXAMPLE}"


def test_readme_exists() -> None:
    assert README.exists(), f"Missing: {README}"


# ── EnvironmentFile ────────────────────────────────────────────────────────────


def test_all_units_have_environment_file() -> None:
    for unit in ALL_UNITS:
        content = _read(unit)
        assert "EnvironmentFile=/etc/kri/kri.env" in content, f"{unit.name}: missing EnvironmentFile=/etc/kri/kri.env"


# ── Restart policy ─────────────────────────────────────────────────────────────


def test_all_units_restart_on_failure() -> None:
    for unit in ALL_UNITS:
        content = _read(unit)
        assert "Restart=on-failure" in content, f"{unit.name}: missing Restart=on-failure"


# ── [Install] section ──────────────────────────────────────────────────────────


def test_all_units_wanted_by_multi_user_target() -> None:
    for unit in ALL_UNITS:
        content = _read(unit)
        assert "WantedBy=multi-user.target" in content, f"{unit.name}: missing WantedBy=multi-user.target"


# ── ExecStart correctness ──────────────────────────────────────────────────────


def test_api_execstart_uses_uvicorn() -> None:
    content = _read(API_UNIT)
    assert "uvicorn fleet_platform.api.main:app" in content, (
        "kri-api.service: ExecStart must invoke uvicorn fleet_platform.api.main:app"
    )


def test_worker_execstart_uses_celery_worker() -> None:
    content = _read(WORKER_UNIT)
    # Must contain the worker sub-command (not beat)
    assert re.search(r"celery\b.*\bworker\b", content), "kri-worker.service: ExecStart must invoke celery ... worker"


def test_beat_execstart_uses_celery_beat() -> None:
    content = _read(BEAT_UNIT)
    assert re.search(r"celery\b.*\bbeat\b", content), "kri-beat.service: ExecStart must invoke celery ... beat"


def test_beat_execstart_uses_redbeat_scheduler() -> None:
    content = _read(BEAT_UNIT)
    assert "redbeat.RedBeatScheduler" in content, (
        "kri-beat.service: ExecStart must specify --scheduler=redbeat.RedBeatScheduler"
    )


# ── api: ExecStartPre runs migrate.sh ─────────────────────────────────────────


def test_api_has_execstartpre_migrate() -> None:
    content = _read(API_UNIT)
    assert "ExecStartPre=" in content and "migrate.sh" in content, (
        "kri-api.service: must have ExecStartPre running migrate.sh"
    )


def test_worker_has_no_execstartpre_migrate() -> None:
    """Worker must NOT run migrations — only the API does."""
    content = _read(WORKER_UNIT)
    assert "ExecStartPre" not in content or "migrate.sh" not in content, (
        "kri-worker.service: should not have ExecStartPre migrate.sh"
    )


def test_beat_has_no_execstartpre_migrate() -> None:
    """Beat must NOT run migrations — only the API does."""
    content = _read(BEAT_UNIT)
    assert "ExecStartPre" not in content or "migrate.sh" not in content, (
        "kri-beat.service: should not have ExecStartPre migrate.sh"
    )


# ── No plaintext secrets in .service files ────────────────────────────────────

# Pattern: lines that look like KEY=<actual_value> where the value is not a
# reference to another env var ($VAR or ${VAR}) and not empty.
# We flag any PASSWORD=..., SECRET=..., TOKEN=... that has a bare literal value.
_SECRET_LINE_RE = re.compile(
    r"^(?:PASSWORD|SECRET|TOKEN|API_KEY)\s*=\s*(?!\$)(?!\s*$).+",
    re.IGNORECASE | re.MULTILINE,
)


def test_no_plaintext_secrets_in_api_unit() -> None:
    content = _read(API_UNIT)
    matches = _SECRET_LINE_RE.findall(content)
    assert not matches, f"kri-api.service contains plaintext secret lines: {matches}"


def test_no_plaintext_secrets_in_worker_unit() -> None:
    content = _read(WORKER_UNIT)
    matches = _SECRET_LINE_RE.findall(content)
    assert not matches, f"kri-worker.service contains plaintext secret lines: {matches}"


def test_no_plaintext_secrets_in_beat_unit() -> None:
    content = _read(BEAT_UNIT)
    matches = _SECRET_LINE_RE.findall(content)
    assert not matches, f"kri-beat.service contains plaintext secret lines: {matches}"


# ── kri.env.example required keys ────────────────────────────────────────────


def test_env_example_has_database_url() -> None:
    content = _read(ENV_EXAMPLE)
    assert "DATABASE_URL=" in content, "kri.env.example: missing DATABASE_URL"


def test_env_example_has_redis_url() -> None:
    content = _read(ENV_EXAMPLE)
    assert "REDIS_URL=" in content, "kri.env.example: missing REDIS_URL"


def test_env_example_has_jwt_secret() -> None:
    content = _read(ENV_EXAMPLE)
    assert "JWT_SECRET=" in content, "kri.env.example: missing JWT_SECRET"


def test_env_example_has_salt_api_vars() -> None:
    content = _read(ENV_EXAMPLE)
    for var in ("SALT_API_URL", "SALT_API_USER", "SALT_API_PASSWORD"):
        assert f"{var}=" in content, f"kri.env.example: missing {var}"


def test_env_example_uses_localhost_for_db() -> None:
    content = _read(ENV_EXAMPLE)
    # Standalone mode should use 127.0.0.1, not a container DNS hostname like 'db'
    db_url_line = next(
        (line for line in content.splitlines() if line.startswith("DATABASE_URL=")),
        None,
    )
    assert db_url_line is not None, "kri.env.example: DATABASE_URL line not found"
    assert "127.0.0.1" in db_url_line, (
        f"kri.env.example: DATABASE_URL should use 127.0.0.1 for standalone mode, got: {db_url_line}"
    )


# ── README mentions systemctl enable ─────────────────────────────────────────


def test_readme_mentions_systemctl_enable() -> None:
    content = _read(README)
    assert "systemctl enable" in content, "deploy/systemd/README.md: must mention 'systemctl enable'"


def test_readme_mentions_all_three_services() -> None:
    content = _read(README)
    for svc in ("kri-api", "kri-worker", "kri-beat"):
        assert svc in content, f"deploy/systemd/README.md: missing reference to {svc}"
