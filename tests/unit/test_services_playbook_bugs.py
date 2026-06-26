"""Tests for playbook service-layer bug fixes (#446, #448, #461) — with behavioural additions (#505)."""

import asyncio
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.dialects import postgresql

_WORKTREE = Path(__file__).resolve().parents[2]
_LIB_SRC = (_WORKTREE / "fleet_platform/api/routes/playbook_library.py").read_text()


def _make_db() -> AsyncMock:
    """Return an AsyncMock db session with a wired execute().scalar_one_or_none() chain."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    result.scalar_one.return_value = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute.return_value = result
    return db


def _compiled(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


# ---------------------------------------------------------------------------
# Fix #448: No db.commit() in service layer
# ---------------------------------------------------------------------------


def test_no_db_commit_in_enable_playbook():
    """Service must NOT commit — only callers commit."""
    from fleet_platform.services.playbook_catalog_svc import enable_playbook

    db = _make_db()
    db.execute.return_value.scalar_one.return_value = MagicMock()
    asyncio.run(
        enable_playbook(
            db,
            source_key="git@example.com",
            source_label="test",
            filename="site.yml",
            entry_type="playbook",
            actor="user@test",
        )
    )
    db.commit.assert_not_awaited()


def test_no_db_commit_in_disable_playbook():
    from fleet_platform.services.playbook_catalog_svc import disable_playbook

    db = _make_db()
    asyncio.run(disable_playbook(db, catalog_id=uuid.uuid4(), actor="user@test"))
    db.commit.assert_not_awaited()


def test_no_db_commit_in_enable_source():
    from fleet_platform.services.playbook_catalog_svc import enable_source

    db = _make_db()
    asyncio.run(
        enable_source(
            db,
            source_key="git@example.com",
            source_label="test",
            discovered=[],
            actor="user@test",
        )
    )
    db.commit.assert_not_awaited()


def test_no_db_commit_in_auto_disable_missing():
    from fleet_platform.services.playbook_catalog_svc import auto_disable_missing

    db = _make_db()
    asyncio.run(
        auto_disable_missing(
            db,
            source_key="git@example.com",
            discovered_filenames=set(),
        )
    )
    db.commit.assert_not_awaited()


def test_no_db_commit_in_add_favorite():
    from fleet_platform.services.playbook_catalog_svc import add_favorite

    db = _make_db()
    asyncio.run(add_favorite(db, user_id=uuid.uuid4(), catalog_id=uuid.uuid4()))
    db.commit.assert_not_awaited()


def test_no_db_commit_in_remove_favorite():
    from fleet_platform.services.playbook_catalog_svc import remove_favorite

    db = _make_db()
    asyncio.run(remove_favorite(db, user_id=uuid.uuid4(), catalog_id=uuid.uuid4()))
    db.commit.assert_not_awaited()


# ---------------------------------------------------------------------------
# Fix #461: enable_playbook uses ON CONFLICT to prevent TOCTOU race
# ---------------------------------------------------------------------------


def test_enable_playbook_uses_on_conflict():
    """enable_playbook must issue an INSERT … ON CONFLICT DO UPDATE statement (#461)."""
    from fleet_platform.services.playbook_catalog_svc import enable_playbook

    db = AsyncMock()
    captured: list = []

    async def capture_execute(stmt, *a, **kw):
        captured.append(stmt)
        result = MagicMock()
        result.scalar_one.return_value = MagicMock()
        return result

    db.execute.side_effect = capture_execute

    asyncio.run(
        enable_playbook(
            db,
            source_key="git@example.com",
            source_label="test",
            filename="site.yml",
            entry_type="playbook",
            actor="user@test",
        )
    )

    assert captured, "enable_playbook must call db.execute"
    sql = _compiled(captured[0]).lower()
    assert "conflict" in sql, "enable_playbook must use INSERT … ON CONFLICT DO UPDATE to prevent TOCTOU race (#461)"


# ---------------------------------------------------------------------------
# P3-5: disable_playbook clears enabled_by / enabled_at
# ---------------------------------------------------------------------------


def _make_disable_db(row):
    """Return an AsyncMock db whose execute() resolves with a plain MagicMock result."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    db.execute.return_value = result
    return db


def test_disable_clears_enabled_by():
    from fleet_platform.services.playbook_catalog_svc import disable_playbook

    row = MagicMock(spec=["enabled", "enabled_by", "enabled_at"])
    row.enabled_by = "some-user"
    row.enabled_at = "2024-01-01"

    db = _make_disable_db(row)
    asyncio.run(disable_playbook(db, catalog_id=uuid.uuid4(), actor="user@test"))
    assert row.enabled_by is None, "disable_playbook must clear enabled_by"


def test_disable_clears_enabled_at():
    from fleet_platform.services.playbook_catalog_svc import disable_playbook

    row = MagicMock(spec=["enabled", "enabled_by", "enabled_at"])
    row.enabled_by = "some-user"
    row.enabled_at = "2024-01-01"

    db = _make_disable_db(row)
    asyncio.run(disable_playbook(db, catalog_id=uuid.uuid4(), actor="user@test"))
    assert row.enabled_at is None, "disable_playbook must clear enabled_at"


# ---------------------------------------------------------------------------
# Fix #446: No sources[i-1] index arithmetic in playbook_library.py
# Absence regression invariant — kept as text guard since the next test is the
# behavioral proof of the same bug; this text check is a cheap second signal.
# ---------------------------------------------------------------------------


def test_source_index_no_arithmetic():
    """No sources[i-1] pattern — must use explicit (dir, source_key) pairing."""
    assert "sources[i - 1]" not in _LIB_SRC and "sources[i-1]" not in _LIB_SRC, (
        "Index arithmetic on sources[] must be removed (Fix #446)"
    )


# ---------------------------------------------------------------------------
# Behavioural: source_key when first source dir absent (#505)
# ---------------------------------------------------------------------------


def test_dir_source_pairs_source_key_correct_when_first_source_absent():
    """_dir_source_pairs must assign the correct source_key to a git source even when
    the built-in /app/playbooks dir is absent (only the git clone dir exists).

    This would FAIL with the old sources[i-1] arithmetic because the git source
    would be assigned index 0's key instead of its own.
    """
    import json
    from pathlib import Path

    git_url = "https://git.example.com/pulse.git"
    fake_clone_path = "/tmp/kri-test-clone-pulse"
    sources_json = json.dumps([{"type": "git", "url": git_url, "label": "pulse"}])

    # Simulate: built-in dir absent, git clone dir present.
    # get_all_playbook_dirs is imported locally inside _dir_source_pairs — patch it at source.
    def fake_get_all_dirs(_sources_json_arg, _builtin_dir):
        return [Path(fake_clone_path)]

    def fake_default_clone_path(_url: str) -> str:
        return fake_clone_path

    def fake_is_dir(self: Path) -> bool:
        return str(self) == fake_clone_path

    with (
        patch("fleet_platform.services.playbook_sources.get_all_playbook_dirs", side_effect=fake_get_all_dirs),
        patch("fleet_platform.services.playbook_sources._default_clone_path", side_effect=fake_default_clone_path),
        patch("pathlib.Path.is_dir", fake_is_dir),
        patch("fleet_platform.api.routes.playbook_library._PLAYBOOKS_DIR", Path("/app/playbooks")),
    ):
        from fleet_platform.api.routes.playbook_library import _dir_source_pairs

        pairs = _dir_source_pairs(sources_json)

    # Must find exactly one pair, and its source_key must be the git URL
    assert len(pairs) == 1, f"expected 1 pair, got {len(pairs)}: {pairs}"
    _d, sk, sl = pairs[0]
    assert sk == git_url, f"source_key must be the git URL '{git_url}', got '{sk}'"
    assert sl == "pulse", f"source_label must be 'pulse', got '{sl}'"
