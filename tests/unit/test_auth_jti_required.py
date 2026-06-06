from pathlib import Path

# Use absolute paths to read from this worktree
_WORKTREE = Path(__file__).parent.parent.parent
_AUTH = (_WORKTREE / "fleet_platform/core/auth.py").read_text()
_ROUTES_AUTH = (_WORKTREE / "fleet_platform/api/routes/auth.py").read_text()


def test_no_permissive_jti_default():
    """jti must not default to empty string — tokens without jti are forged."""
    assert 'claims.get("jti", "")' not in _AUTH, "must not use empty-string default for jti in auth.py"
    assert 'claims.get("jti", "")' not in _ROUTES_AUTH, "must not use empty-string default for jti in routes/auth.py"


def test_jti_none_rejected():
    """Missing jti claim must be explicitly rejected."""
    assert "if not jti" in _AUTH, "must explicitly reject tokens with no jti in auth.py"


def test_jti_missing_raises_401():
    """Error message must indicate jti is required."""
    assert (
        "missing required jti" in _AUTH.lower() or "missing jti claim" in _AUTH.lower() or "jti claim" in _AUTH.lower()
    ), "must have error message about missing jti in auth.py"
