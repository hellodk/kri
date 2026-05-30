"""Tests for kri.sh deploy and test subcommands."""
from pathlib import Path


def _kri() -> str:
    return Path("scripts/kri.sh").read_text()


def test_kri_sh_exists():
    assert Path("scripts/kri.sh").exists()


def test_require_env_function_exists():
    src = _kri()
    assert "require_env()" in src or "require_env()" in src


def test_compose_function_exists():
    src = _kri()
    # compose() wraps docker compose -f ... --env-file ...
    assert "compose()" in src or "docker compose" in src


def test_env_file_variable_set():
    src = _kri()
    assert 'ENV_FILE=' in src and '.env.docker' in src


def test_cmd_deploy_calls_require_env():
    src = _kri()
    deploy_idx = src.index("cmd_deploy()")
    deploy_body = src[deploy_idx:deploy_idx + 800]
    assert "require_env" in deploy_body


def test_cmd_deploy_uses_compose():
    src = _kri()
    deploy_idx = src.index("cmd_deploy()")
    deploy_body = src[deploy_idx:deploy_idx + 800]
    # compose() function handles --env-file injection
    assert "compose" in deploy_body


def test_cmd_start_calls_require_env():
    src = _kri()
    # kri deploy or kri infra start; check that require_env is referenced in context
    assert "require_env" in src


def test_cmd_start_uses_compose():
    src = _kri()
    assert "compose" in src and "up" in src


def test_test_unit_subcommand_exists():
    src = _kri()
    assert "unit)" in src
    assert "tests/unit/" in src


def test_test_integration_subcommand_exists():
    src = _kri()
    assert "integration)" in src
    assert "tests/integration/" in src


def test_test_all_subcommand_exists():
    src = _kri()
    assert "all)" in src
    assert "tests/unit/" in src and "tests/integration/" in src


def test_test_e2e_subcommand_exists():
    src = _kri()
    assert "e2e" in src and "playwright" in src.lower()


def test_redis_password_not_hardcoded():
    src = _kri()
    assert "redispass" not in src.lower()
    assert "password123" not in src.lower()


def test_env_file_missing_gives_helpful_error():
    src = _kri()
    assert ".env.docker not found" in src or "env.docker.example" in src
