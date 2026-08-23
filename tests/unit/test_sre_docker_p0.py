# tests/unit/test_sre_docker_p0.py
"""
P0 security regression tests for issues #80, #82, #88, #90, #91.

These tests verify that the five critical Docker/SRE hardening fixes are in
place. They are purely file-inspection tests — no network, DB, or Docker
required.
"""

import re
from pathlib import Path

# Repo root is two levels up from tests/unit/
REPO_ROOT = Path(__file__).parent.parent.parent


# ── #80: JWT_SECRET is a placeholder, not a real hex secret ──────────────────


def test_env_docker_example_has_placeholder_jwt_secret():
    """`.env.docker.example` must contain a CHANGE_ME placeholder, not a real hex secret."""
    env_file = REPO_ROOT / ".env.docker.example"
    assert env_file.exists(), ".env.docker.example does not exist"
    content = env_file.read_text()
    real_secret_pattern = re.compile(r"JWT_SECRET=[0-9a-fA-F]{32,}")
    assert not real_secret_pattern.search(content), ".env.docker.example still contains a real JWT_SECRET hex value"
    assert "CHANGE_ME" in content, ".env.docker.example JWT_SECRET must contain CHANGE_ME placeholder"


def test_env_docker_example_exists():
    """.env.docker.example must exist at the repo root with placeholder values."""
    example_file = REPO_ROOT / ".env.docker.example"
    assert example_file.exists(), ".env.docker.example does not exist at repo root"
    content = example_file.read_text()
    assert "CHANGE_ME" in content, ".env.docker.example must contain CHANGE_ME placeholders for secrets"


# ── #80: .gitignore must exclude .env.docker ─────────────────────────────────


def test_gitignore_excludes_env_docker():
    """.gitignore must list .env.docker so the real secrets file is never committed."""
    gitignore = REPO_ROOT / ".gitignore"
    assert gitignore.exists(), ".gitignore does not exist"
    content = gitignore.read_text()
    assert ".env.docker" in content, ".gitignore must explicitly list .env.docker"


# ── #82: No Docker socket in worker ──────────────────────────────────────────


def test_worker_has_no_docker_socket():
    """docker-compose.yml worker service must not mount /var/run/docker.sock."""
    import yaml  # pyyaml is a dev dependency

    compose_file = REPO_ROOT / "deploy" / "docker-compose.yml"
    assert compose_file.exists(), "deploy/docker-compose.yml does not exist"
    with compose_file.open() as f:
        cfg = yaml.safe_load(f)

    worker_vols = cfg["services"]["worker"].get("volumes", [])
    socket_mounts = [str(v) for v in worker_vols if "docker.sock" in str(v)]
    assert not socket_mounts, (
        f"Worker service still mounts Docker socket: {socket_mounts}. "
        "Remove /var/run/docker.sock from worker volumes (issue #82)."
    )


def test_worker_has_no_docker_binary_mount():
    """docker-compose.yml worker must not bind-mount the host Docker binary."""
    import yaml

    compose_file = REPO_ROOT / "deploy" / "docker-compose.yml"
    with compose_file.open() as f:
        cfg = yaml.safe_load(f)

    worker_vols = cfg["services"]["worker"].get("volumes", [])
    docker_bin_mounts = [str(v) for v in worker_vols if "/usr/bin/docker" in str(v)]
    assert not docker_bin_mounts, (
        f"Worker service still bind-mounts the Docker binary: {docker_bin_mounts}. "
        "Remove /usr/bin/docker from worker volumes (issue #82)."
    )


# ── #88: Dockerfile runs as non-root ─────────────────────────────────────────


def test_dockerfile_api_has_user_directive():
    """deploy/Dockerfile.api must contain a USER directive to run as non-root."""
    dockerfile = REPO_ROOT / "deploy" / "Dockerfile.api"
    assert dockerfile.exists(), "deploy/Dockerfile.api does not exist"
    content = dockerfile.read_text()
    assert "USER appuser" in content, (
        "Dockerfile.api must have 'USER appuser' directive (issue #88). "
        "Running containers as root is a P0 security risk."
    )


def test_dockerfile_api_creates_appuser():
    """deploy/Dockerfile.api must create the appuser account."""
    dockerfile = REPO_ROOT / "deploy" / "Dockerfile.api"
    content = dockerfile.read_text()
    assert "useradd" in content and "appuser" in content, (
        "Dockerfile.api must create the appuser account with useradd (issue #88)."
    )


# ── #90: Advisory lock migration script ──────────────────────────────────────


def test_migrate_sh_exists():
    """deploy/migrate.sh must exist."""
    migrate_sh = REPO_ROOT / "deploy" / "migrate.sh"
    assert migrate_sh.exists(), "deploy/migrate.sh does not exist (issue #90)"


def test_migrate_sh_has_advisory_lock():
    """deploy/migrate.sh must use pg_advisory_lock to prevent concurrent migrations."""
    migrate_sh = REPO_ROOT / "deploy" / "migrate.sh"
    content = migrate_sh.read_text()
    assert "pg_advisory_lock" in content, (
        "deploy/migrate.sh must call pg_advisory_lock() (issue #90). "
        "Without the lock, concurrent API replicas can corrupt the migration state."
    )
    assert "pg_advisory_unlock" in content, (
        "deploy/migrate.sh must release the lock via pg_advisory_unlock() (issue #90)."
    )


def test_docker_compose_api_uses_migrate_sh():
    """api service must boot through api-entrypoint.sh, which execs migrate.sh then uvicorn (issue #90 + #1050)."""
    import yaml

    compose_file = REPO_ROOT / "deploy" / "docker-compose.yml"
    with compose_file.open() as f:
        cfg = yaml.safe_load(f)

    api_command = " ".join(cfg["services"]["api"].get("command", []))
    assert "api-entrypoint.sh" in api_command, (
        f"docker-compose.yml api service must boot via api-entrypoint.sh (#1050). Current command: {api_command!r}"
    )
    entrypoint = (REPO_ROOT / "deploy" / "api-entrypoint.sh").read_text()
    assert "migrate.sh" in entrypoint, "api-entrypoint.sh must still run migrate.sh before exec uvicorn"


def test_dockerfile_api_copies_migrate_sh():
    """deploy/Dockerfile.api must COPY migrate.sh into the image."""
    dockerfile = REPO_ROOT / "deploy" / "Dockerfile.api"
    content = dockerfile.read_text()
    assert "migrate.sh" in content, "Dockerfile.api must COPY deploy/migrate.sh into the image (issue #90)."


# ── #91: No personal ~/.ssh in worker ────────────────────────────────────────


def test_worker_has_no_personal_ssh_mount():
    """docker-compose.yml worker must not mount the operator's personal ~/.ssh."""
    import yaml

    compose_file = REPO_ROOT / "deploy" / "docker-compose.yml"
    with compose_file.open() as f:
        cfg = yaml.safe_load(f)

    worker_vols = cfg["services"]["worker"].get("volumes", [])
    personal_ssh = [str(v) for v in worker_vols if "~/.ssh" in str(v)]
    assert not personal_ssh, (
        f"Worker mounts personal SSH directory: {personal_ssh}. "
        "Remove ~/.ssh from worker volumes and use a dedicated keypair (issue #91)."
    )


def test_worker_uses_configurable_ssh_dir():
    """docker-compose.yml worker SSH mount must use WORKER_SSH_DIR variable."""
    compose_file = REPO_ROOT / "deploy" / "docker-compose.yml"
    content = compose_file.read_text()
    assert "WORKER_SSH_DIR" in content, (
        "docker-compose.yml worker SSH mount must be configurable via WORKER_SSH_DIR env var (issue #91)."
    )


def test_deploy_ssh_gitkeep_exists():
    """deploy/ssh/.gitkeep must exist to preserve the dedicated SSH key directory."""
    gitkeep = REPO_ROOT / "deploy" / "ssh" / ".gitkeep"
    assert gitkeep.exists(), (
        "deploy/ssh/.gitkeep does not exist. "
        "Create the directory and add .gitkeep so the mount point is committed (issue #91)."
    )


def test_gitignore_excludes_deploy_ssh_keys():
    """.gitignore must exclude deploy/ssh/* to prevent SSH private key commits."""
    gitignore = REPO_ROOT / ".gitignore"
    content = gitignore.read_text()
    assert "deploy/ssh/*" in content, ".gitignore must list deploy/ssh/* to exclude SSH private keys (issue #91)."
    # .gitkeep should NOT be excluded
    assert "!deploy/ssh/.gitkeep" in content, (
        ".gitignore must whitelist deploy/ssh/.gitkeep so the directory is tracked."
    )
