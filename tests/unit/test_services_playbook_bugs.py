"""Tests for playbook service-layer bug fixes (#446, #448, #461)."""

from pathlib import Path

_CATALOG_SRC = Path("fleet_platform/services/playbook_catalog_svc.py").read_text()
_LIB_SRC = Path("fleet_platform/api/routes/playbook_library.py").read_text()


def _extract_fn(src: str, fn_name: str) -> str:
    """Extract a function body from source text."""
    start = src.find(f"async def {fn_name}")
    if start == -1:
        start = src.find(f"def {fn_name}")
    end = src.find("\nasync def ", start + 1)
    if end == -1:
        end = src.find("\ndef ", start + 1)
    return src[start : end if end != -1 else start + 3000]


# ---------------------------------------------------------------------------
# Fix #448: No db.commit() in service layer
# ---------------------------------------------------------------------------


def test_no_db_commit_in_enable_playbook():
    """Service must NOT commit — only callers commit."""
    segment = _extract_fn(_CATALOG_SRC, "enable_playbook")
    assert "await db.commit()" not in segment, "enable_playbook must not call db.commit()"


def test_no_db_commit_in_disable_playbook():
    segment = _extract_fn(_CATALOG_SRC, "disable_playbook")
    assert "await db.commit()" not in segment, "disable_playbook must not call db.commit()"


def test_no_db_commit_in_enable_source():
    segment = _extract_fn(_CATALOG_SRC, "enable_source")
    assert "await db.commit()" not in segment, "enable_source must not call db.commit()"


def test_no_db_commit_in_auto_disable_missing():
    segment = _extract_fn(_CATALOG_SRC, "auto_disable_missing")
    assert "await db.commit()" not in segment, "auto_disable_missing must not call db.commit()"


def test_no_db_commit_in_add_favorite():
    segment = _extract_fn(_CATALOG_SRC, "add_favorite")
    assert "await db.commit()" not in segment, "add_favorite must not call db.commit()"


def test_no_db_commit_in_remove_favorite():
    segment = _extract_fn(_CATALOG_SRC, "remove_favorite")
    assert "await db.commit()" not in segment, "remove_favorite must not call db.commit()"


# ---------------------------------------------------------------------------
# Fix #461: enable_playbook uses ON CONFLICT to prevent TOCTOU race
# ---------------------------------------------------------------------------


def test_enable_playbook_uses_on_conflict():
    assert "on_conflict_do_update" in _CATALOG_SRC, "enable_playbook must use INSERT ON CONFLICT to prevent TOCTOU race"


# ---------------------------------------------------------------------------
# P3-5: disable_playbook clears enabled_by / enabled_at
# ---------------------------------------------------------------------------


def test_disable_clears_enabled_by():
    segment = _extract_fn(_CATALOG_SRC, "disable_playbook")
    assert "enabled_by = None" in segment, "disable_playbook must clear enabled_by"


def test_disable_clears_enabled_at():
    segment = _extract_fn(_CATALOG_SRC, "disable_playbook")
    assert "enabled_at = None" in segment, "disable_playbook must clear enabled_at"


# ---------------------------------------------------------------------------
# Fix #446: No sources[i-1] index arithmetic in playbook_library.py
# ---------------------------------------------------------------------------


def test_source_index_no_arithmetic():
    """No sources[i-1] pattern — must use explicit (dir, source_key) pairing."""
    assert "sources[i - 1]" not in _LIB_SRC and "sources[i-1]" not in _LIB_SRC, (
        "Index arithmetic on sources[] must be removed (Fix #446)"
    )
