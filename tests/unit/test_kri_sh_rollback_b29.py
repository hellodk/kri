"""Tests for #101/#102: kri.sh rolling deploy and rollback commands."""

from pathlib import Path

KRI_SH = (Path(__file__).parent.parent.parent / "scripts/kri").read_text()


def test_rolling_deploy_function_exists():
    assert "cmd_rolling_deploy" in KRI_SH


def test_rollback_function_exists():
    assert "cmd_rollback" in KRI_SH


def test_rolling_deploy_dispatched():
    assert "rolling-deploy)" in KRI_SH


def test_rollback_dispatched():
    assert "rollback)" in KRI_SH


def test_rolling_deploy_restarts_api_last():
    start = KRI_SH.index("cmd_rolling_deploy()")
    end = KRI_SH.index("cmd_rollback()")
    rolling_body = KRI_SH[start:end]
    # Find ALL lines that contain both beat and api (tagging loop, restart loop)
    loop_lines = [line for line in rolling_body.splitlines() if "beat" in line and "api" in line]
    # The restart loop should have api AFTER beat (api is last — highest blast radius)
    assert any(line.find("beat") < line.find("api") for line in loop_lines), (
        f"At least one loop must have beat before api. Lines found: {loop_lines}"
    )


def test_stateful_services_excluded_from_rolling():
    # db, redis, salt-master must not be in rolling restart list
    start = KRI_SH.index("cmd_rolling_deploy()")
    end = KRI_SH.index("cmd_rollback()")
    rolling_body = KRI_SH[start:end]
    for stateful in ['"db"', '"redis"', '"salt-master"']:
        assert stateful not in rolling_body, f"{stateful} must not appear in rolling deploy services"


def test_version_tagged_before_rollback():
    assert ":previous" in KRI_SH


def test_kri_sh_bash_syntax():
    import subprocess

    result = subprocess.run(
        ["bash", "-n", str(Path(__file__).parent.parent.parent / "scripts/kri")], capture_output=True
    )
    assert result.returncode == 0, f"bash -n failed: {result.stderr.decode()}"
