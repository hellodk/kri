import json
from pathlib import Path
from unittest.mock import patch

from fleet_platform.services.playbook_sources import (
    _default_clone_path,
    _sync_git_source,
    _translate_path,
    get_all_playbook_dirs,
    sync_all_git_sources,
)

# ---------------------------------------------------------------------------
# _translate_path
# ---------------------------------------------------------------------------


def test_translate_path_no_map(monkeypatch):
    monkeypatch.delenv("PLAYBOOK_PATH_MAP", raising=False)
    assert _translate_path("/home/dk/foo") == "/home/dk/foo"


def test_translate_path_match(monkeypatch):
    monkeypatch.setenv("PLAYBOOK_PATH_MAP", "/home/dk:/mnt")
    assert _translate_path("/home/dk/foo") == "/mnt/foo"


def test_translate_path_no_match(monkeypatch):
    monkeypatch.setenv("PLAYBOOK_PATH_MAP", "/other:/mnt")
    assert _translate_path("/home/dk/foo") == "/home/dk/foo"


def test_translate_path_first_match_wins(monkeypatch):
    monkeypatch.setenv("PLAYBOOK_PATH_MAP", "/home/dk:/mnt,/home:/container")
    assert _translate_path("/home/dk/foo") == "/mnt/foo"


def test_translate_path_malformed_entry_skipped(monkeypatch):
    monkeypatch.setenv("PLAYBOOK_PATH_MAP", "badentrynocolon,/a:/b")
    assert _translate_path("/home/dk/foo") == "/home/dk/foo"


# ---------------------------------------------------------------------------
# _default_clone_path
# ---------------------------------------------------------------------------


def test_default_clone_path_strips_dot_git():
    result = _default_clone_path("https://github.com/org/myrepo.git")
    assert result.endswith("/myrepo")


def test_default_clone_path_no_dot_git():
    result = _default_clone_path("https://github.com/org/myrepo")
    assert result.endswith("/myrepo")


# ---------------------------------------------------------------------------
# _sync_git_source
# ---------------------------------------------------------------------------


def test_sync_git_source_pulls_if_exists(tmp_path):
    with patch("fleet_platform.services.playbook_sources.subprocess.run") as mock_run:
        result = _sync_git_source(
            url="https://github.com/org/repo.git",
            branch="main",
            local_path=str(tmp_path),
        )
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args[:4] == ["git", "-C", str(tmp_path), "pull"]
    assert "--ff-only" in args
    assert result == tmp_path


def test_sync_git_source_clones_if_not_exists(tmp_path):
    clone_target = tmp_path / "new-repo"
    with patch("fleet_platform.services.playbook_sources.subprocess.run") as mock_run:
        result = _sync_git_source(
            url="https://github.com/org/repo.git",
            branch="main",
            local_path=str(clone_target),
        )
    # _sync_git_source calls both clone AND pull (used for explicit sync operations)
    assert mock_run.call_count == 2
    clone_call_args = mock_run.call_args_list[0][0][0]
    assert clone_call_args[0] == "git"
    assert "clone" in clone_call_args
    pull_call_args = mock_run.call_args_list[1][0][0]
    assert "pull" in pull_call_args
    assert result == clone_target


# ---------------------------------------------------------------------------
# get_all_playbook_dirs
# ---------------------------------------------------------------------------


def test_get_all_playbook_dirs_no_settings(tmp_path):
    result = get_all_playbook_dirs(None, tmp_path)
    assert result == [tmp_path]


def test_get_all_playbook_dirs_invalid_json(tmp_path):
    result = get_all_playbook_dirs("not-json", tmp_path)
    assert result == [tmp_path]


def test_get_all_playbook_dirs_local_existing(tmp_path):
    extra_dir = tmp_path / "extra"
    extra_dir.mkdir()
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    settings = json.dumps([{"type": "local", "path": str(extra_dir)}])
    result = get_all_playbook_dirs(settings, builtin)
    assert builtin in result
    assert extra_dir in result
    assert result.index(builtin) < result.index(extra_dir)


def test_get_all_playbook_dirs_local_nonexistent(tmp_path):
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    settings = json.dumps([{"type": "local", "path": str(tmp_path / "does-not-exist")}])
    result = get_all_playbook_dirs(settings, builtin)
    assert result == [builtin]


def test_get_all_playbook_dirs_git_source(tmp_path):
    """get_all_playbook_dirs uses the existing clone cache — no git pull on list."""
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    # Simulate an already-cloned repo in the cache dir
    cached_repo = tmp_path / "cached-repo"
    cached_repo.mkdir()
    settings = json.dumps(
        [{"type": "git", "url": "https://github.com/org/repo.git", "branch": "main", "local_path": str(cached_repo)}]
    )
    # _sync_git_source must NOT be called — get_all_playbook_dirs should use cache as-is
    with patch(
        "fleet_platform.services.playbook_sources._sync_git_source",
    ) as mock_sync:
        result = get_all_playbook_dirs(settings, builtin)
    mock_sync.assert_not_called()  # no git pull on every list request
    assert builtin in result
    assert cached_repo in result


def test_get_all_playbook_dirs_git_error_skipped(tmp_path):
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    settings = json.dumps([{"type": "git", "url": "https://github.com/org/repo.git", "branch": "main"}])
    with patch(
        "fleet_platform.services.playbook_sources._sync_git_source",
        side_effect=Exception("network failure"),
    ):
        result = get_all_playbook_dirs(settings, builtin)
    assert result == [builtin]


# ---------------------------------------------------------------------------
# sync_all_git_sources
# ---------------------------------------------------------------------------


def test_sync_all_git_sources_none():
    result = sync_all_git_sources(None)
    assert result == []


def test_sync_all_git_sources_skips_local():
    settings = json.dumps([{"type": "local", "path": "/some/path"}])
    with patch("fleet_platform.services.playbook_sources._sync_git_source") as mock_sync:
        result = sync_all_git_sources(settings)
    mock_sync.assert_not_called()
    assert result == []


def test_sync_all_git_sources_success():
    url = "https://github.com/org/repo.git"
    settings = json.dumps([{"type": "git", "url": url, "branch": "main"}])
    with patch(
        "fleet_platform.services.playbook_sources._sync_git_source",
        return_value=Path("/fake/path"),
    ):
        result = sync_all_git_sources(settings)
    assert len(result) == 1
    assert result[0]["status"] == "ok"
    assert result[0]["url"] == url
    assert result[0]["index"] == 0


def test_sync_all_git_sources_error():
    url = "https://github.com/org/broken.git"
    settings = json.dumps([{"type": "git", "url": url, "branch": "main"}])
    with patch(
        "fleet_platform.services.playbook_sources._sync_git_source",
        side_effect=Exception("auth failed"),
    ):
        result = sync_all_git_sources(settings)
    assert len(result) == 1
    assert result[0]["status"] == "error"
    assert result[0]["url"] == url
    assert "auth failed" in result[0]["error"]
    assert result[0]["index"] == 0
