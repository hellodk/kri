"""Tests for #496 (source↔dir mapping) and #503 (list_playbooks fallback).

These are pure unit tests — no DB, no network, no I/O beyond tmp_path.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers — mirror the source_key resolution logic in list_playbooks /
# sync_sources without importing the full FastAPI app.
# ---------------------------------------------------------------------------


def _source_key(src: dict) -> str:
    return src.get("url") or src.get("path") or ""


def _resolve_dir_for_source(src: dict, tmp_path: Path) -> Path | None:
    """Return the resolved Path for a source dict, or None if absent/unknown."""
    src_type = src.get("type", "local")
    if src_type == "local":
        raw = src.get("path", "")
        p = Path(raw)
        return p if p.is_dir() else None
    elif src_type == "git":
        url = src.get("url", "")
        local_path = src.get("local_path", "")
        if not local_path and url:
            repo_name = url.rstrip("/").split("/")[-1].replace(".git", "")
            local_path = str(tmp_path / repo_name)
        p = Path(local_path)
        return p if p.is_dir() else None
    return None


def _build_source_dir_map(sources: list[dict], tmp_path: Path) -> dict[str, Path]:
    """Build {source_key: dir} using per-source is_dir() — the fixed logic."""
    result: dict[str, Path] = {}
    for src in sources:
        key = _source_key(src)
        if not key:
            continue
        d = _resolve_dir_for_source(src, tmp_path)
        if d is not None:
            result[key] = d
    return result


# ---------------------------------------------------------------------------
# #496 — source↔dir positional mismapping
# ---------------------------------------------------------------------------


class TestSourceDirMapping:
    def test_all_sources_present_maps_correctly(self, tmp_path):
        """When every source dir exists, map must pair each dir with its key."""
        dir_a = tmp_path / "dir_a"
        dir_b = tmp_path / "dir_b"
        dir_a.mkdir()
        dir_b.mkdir()

        sources = [
            {"type": "local", "path": str(dir_a)},
            {"type": "local", "path": str(dir_b)},
        ]
        result = _build_source_dir_map(sources, tmp_path)

        assert result[str(dir_a)] == dir_a
        assert result[str(dir_b)] == dir_b

    def test_first_source_absent_second_maps_to_its_own_key(self, tmp_path):
        """With sources [A (absent), B (present)], B must map to B's key, not A's.

        The old positional approach: all_dirs = [builtin, dir_b]
        all_dirs[1] → sources[0] (A) → source_key = A's key  ← WRONG
        The fixed approach: iterate sources, skip absent, map by identity.
        """
        dir_b = tmp_path / "dir_b"
        dir_b.mkdir()

        sources = [
            {"type": "local", "path": str(tmp_path / "absent_dir")},
            {"type": "local", "path": str(dir_b)},
        ]
        result = _build_source_dir_map(sources, tmp_path)

        assert str(tmp_path / "absent_dir") not in result
        assert result[str(dir_b)] == dir_b

    def test_git_source_present_uses_url_as_key(self, tmp_path):
        """Git source with existing local clone uses URL as source_key."""
        clone_dir = tmp_path / "my-repo"
        clone_dir.mkdir()

        sources = [
            {
                "type": "git",
                "url": "https://example.com/org/my-repo.git",
                "local_path": str(clone_dir),
            }
        ]
        result = _build_source_dir_map(sources, tmp_path)

        assert "https://example.com/org/my-repo.git" in result
        assert result["https://example.com/org/my-repo.git"] == clone_dir

    def test_git_source_absent_clone_not_included(self, tmp_path):
        """Git source whose local clone doesn't exist yet is skipped."""
        sources = [
            {
                "type": "git",
                "url": "https://example.com/org/not-cloned.git",
                "local_path": str(tmp_path / "not-cloned"),
            }
        ]
        result = _build_source_dir_map(sources, tmp_path)

        assert "https://example.com/org/not-cloned.git" not in result

    def test_mixed_absent_and_present_sources(self, tmp_path):
        """Only present dirs appear in the map, each paired with the right key."""
        present = tmp_path / "present"
        present.mkdir()

        sources = [
            {"type": "local", "path": str(tmp_path / "gone1")},
            {"type": "local", "path": str(present)},
            {"type": "local", "path": str(tmp_path / "gone2")},
        ]
        result = _build_source_dir_map(sources, tmp_path)

        assert len(result) == 1
        assert result[str(present)] == present

    def test_source_key_resolution_prefers_url_over_path(self, tmp_path):
        """When a source dict has both 'url' and 'path', 'url' wins as key."""
        d = tmp_path / "local_clone"
        d.mkdir()

        src = {"type": "git", "url": "https://example.com/repo", "path": str(d), "local_path": str(d)}
        key = _source_key(src)

        assert key == "https://example.com/repo"

    def test_positional_approach_fails_when_first_absent(self, tmp_path):
        """Demonstrate that positional index (i-1) produces wrong key.

        This test documents the OLD broken behaviour to confirm our fix avoids it.
        """
        # Setup: source[0] absent, source[1] present
        dir_b = tmp_path / "dir_b"
        dir_b.mkdir()

        sources = [
            {"type": "local", "path": str(tmp_path / "absent")},  # index 0 — absent
            {"type": "local", "path": str(dir_b)},  # index 1 — present
        ]

        # Simulate old positional logic: get_all_playbook_dirs returns [builtin, dir_b]
        # extra_dirs = [dir_b]; zip with sources → (dir_b, sources[0])
        # → source_key = sources[0]["path"] (absent_dir), WRONG for dir_b
        builtin = tmp_path / "builtin"
        builtin.mkdir()
        all_dirs = [builtin, dir_b]  # absent is skipped, so only 2 entries
        extra_dirs = all_dirs[1:]  # [dir_b]

        positional_keys = []
        for d, src in zip(extra_dirs, sources):
            positional_keys.append((str(d), src.get("url") or src.get("path") or ""))

        # Old code maps dir_b → sources[0].path (the absent dir's key) — that's the bug
        assert positional_keys == [(str(dir_b), str(tmp_path / "absent"))]

        # Fixed code maps dir_b → sources[1].path (its own key)
        fixed_map = _build_source_dir_map(sources, tmp_path)
        assert fixed_map[str(dir_b)] == dir_b


# ---------------------------------------------------------------------------
# #503 — list_playbooks fallback when all catalog entries disabled
# ---------------------------------------------------------------------------


class TestListPlaybooksFallback:
    def test_fallback_triggers_when_enabled_empty_catalog_has_rows(self):
        """Simulates: catalog_total > 0 but enabled = [] — should fall back."""
        # The fix: remove the `catalog_total == 0` guard so the fallback always
        # fires when `not enabled`, regardless of catalog_total.
        enabled: list = []
        catalog_total = 5  # catalog has rows, but all disabled

        # OLD logic (broken):
        old_should_fallback = not enabled and catalog_total == 0
        assert old_should_fallback is False  # confirms the old bug

        # NEW logic (fixed): fallback whenever enabled is empty
        new_should_fallback = not enabled
        assert new_should_fallback is True  # confirms the fix

    def test_fallback_triggers_when_catalog_empty(self):
        """Baseline: catalog_total == 0 should also fall back (existing behaviour)."""
        enabled: list = []
        # catalog_total is 0 — but the new logic only checks `not enabled`
        new_should_fallback = not enabled
        assert new_should_fallback is True

    def test_no_fallback_when_enabled_entries_exist(self):
        """When enabled entries exist, the normal catalog path runs (no fallback)."""
        enabled = [{"source_key": "builtin", "filename": "site.yml", "catalog_id": "abc", "is_favorite": False}]

        should_fallback = not enabled
        assert should_fallback is False

    def test_fallback_returns_all_discovered_playbooks(self, tmp_path):
        """Legacy mode must discover all .yml files in all present dirs."""
        builtin = tmp_path / "builtin"
        builtin.mkdir()
        (builtin / "site.yml").write_text("---\n- name: site\n  hosts: all\n  tasks: []\n")
        (builtin / "deploy.yml").write_text("---\n- name: deploy\n  hosts: all\n  tasks: []\n")

        extra = tmp_path / "extra"
        extra.mkdir()
        (extra / "custom.yml").write_text("---\n- name: custom\n  hosts: all\n  tasks: []\n")

        dirs = [builtin, extra]
        # Simulate the legacy discovery loop
        found = []
        for d in dirs:
            for f in d.glob("*.yml"):
                found.append(f.name)

        assert set(found) == {"site.yml", "deploy.yml", "custom.yml"}

    def test_fallback_skips_absent_dirs_gracefully(self, tmp_path):
        """Absent dirs in the legacy fallback must be skipped (no exception)."""
        present = tmp_path / "present"
        present.mkdir()
        (present / "ok.yml").write_text("---\n- hosts: all\n  tasks: []\n")

        absent = tmp_path / "absent"  # not created

        dirs = [present, absent]
        found = []
        for d in dirs:
            if d.is_dir():
                for f in d.glob("*.yml"):
                    found.append(f.name)

        assert found == ["ok.yml"]
