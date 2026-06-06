"""Security tests for seeding scripts (issue #106)."""


def test_seed_py_does_not_exist():
    """scripts/seed.py must not exist — it creates accounts with hardcoded 'changeme' password."""
    from pathlib import Path

    seed = Path(__file__).parent.parent.parent / "scripts/seed.py"
    assert not seed.exists(), "scripts/seed.py must be deleted — it creates insecure accounts"


def test_seed_users_has_no_hardcoded_password():
    """scripts/seed_users.py must not contain hardcoded passwords."""
    from pathlib import Path

    seed = Path(__file__).parent.parent.parent / "scripts/seed_users.py"
    if not seed.exists():
        return  # script may not exist yet
    content = seed.read_text()
    assert "changeme" not in content.lower(), "seed_users.py must not contain hardcoded 'changeme' password"
    assert '"password"' not in content or "generate" in content or "random" in content or "secrets" in content
