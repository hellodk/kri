"""Tests for kri.sh diagnose command (issue #5 — offline node investigation)."""

from pathlib import Path


def _kri() -> str:
    return Path("scripts/kri.sh").read_text()


def test_diagnose_command_exists():
    assert "cmd_diagnose" in _kri()


def test_diagnose_dispatched():
    assert "diagnose)" in _kri()


def test_diagnose_checks_network():
    src = _kri()
    diagnose_idx = src.index("cmd_diagnose()")
    body = src[diagnose_idx : diagnose_idx + 2000]
    assert "ping" in body


def test_diagnose_checks_ssh_port():
    src = _kri()
    diagnose_idx = src.index("cmd_diagnose()")
    body = src[diagnose_idx : diagnose_idx + 2000]
    assert "22" in body and ("tcp" in body or "ssh" in body.lower())


def test_diagnose_checks_salt_key():
    src = _kri()
    diagnose_idx = src.index("cmd_diagnose()")
    body = src[diagnose_idx : diagnose_idx + 2000]
    assert "salt-key" in body


def test_diagnose_checks_api():
    src = _kri()
    diagnose_idx = src.index("cmd_diagnose()")
    body = src[diagnose_idx : diagnose_idx + 5000]
    assert "localhost:8000" in body or "/health/ready" in body


def test_diagnose_shows_rebootstrap_steps():
    src = _kri()
    diagnose_idx = src.index("cmd_diagnose()")
    body = src[diagnose_idx : diagnose_idx + 5000]
    assert "bootstrap" in body.lower()


def test_diagnose_requires_target_arg():
    src = _kri()
    diagnose_idx = src.index("cmd_diagnose()")
    body = src[diagnose_idx : diagnose_idx + 300]
    assert "Usage" in body or "usage" in body or "target" in body


def test_diagnose_in_help_text():
    src = _kri()
    assert "diagnose" in src and "offline" in src
