"""Tests for kri.sh deploy fix and test subcommands."""
from pathlib import Path


def _kri() -> str:
    return Path("scripts/kri.sh").read_text()


def test_kri_sh_exists():
    assert Path("scripts/kri.sh").exists()


def test_require_env_file_function_exists():
    src = _kri()
    assert "require_env_file" in src


def test_compose_env_function_exists():
    src = _kri()
    assert "compose_env" in src


def test_env_file_variable_set():
    src = _kri()
    assert 'ENV_FILE=' in src and '.env.docker' in src


def test_cmd_deploy_calls_require_env_file():
    src = _kri()
    deploy_idx = src.index("cmd_deploy()")
    deploy_body = src[deploy_idx:deploy_idx + 600]
    assert "require_env_file" in deploy_body


def test_cmd_deploy_passes_env_file_to_compose():
    src = _kri()
    deploy_idx = src.index("cmd_deploy()")
    deploy_body = src[deploy_idx:deploy_idx + 600]
    assert "compose_env" in deploy_body


def test_cmd_start_calls_require_env_file():
    src = _kri()
    start_idx = src.index("cmd_start()")
    start_body = src[start_idx:start_idx + 400]
    assert "require_env_file" in start_body


def test_cmd_start_passes_env_file_to_compose():
    src = _kri()
    start_idx = src.index("cmd_start()")
    start_body = src[start_idx:start_idx + 400]
    assert "compose_env" in start_body


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
