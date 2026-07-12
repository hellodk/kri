"""Source-contract tests for #1005 playbook_library async follow-up (#999).

`_dir_source_pairs` called `get_all_playbook_dirs` (which can perform a blocking
git clone/fetch) directly inside a SYNC helper, so it could not be wrapped in
asyncio.to_thread. The fix makes `_dir_source_pairs` async, awaits
`asyncio.to_thread(get_all_playbook_dirs, ...)`, and updates all call sites in
this file to await it.
"""

from pathlib import Path

PLAYBOOK_LIBRARY_PATH = Path(__file__).parent.parent.parent / "fleet_platform/api/routes/playbook_library.py"


def load() -> str:
    return PLAYBOOK_LIBRARY_PATH.read_text()


class TestDirSourcePairsIsAsync:
    def test_imports_asyncio(self) -> None:
        src = load()
        assert "import asyncio" in src

    def test_dir_source_pairs_is_async_def(self) -> None:
        src = load()
        assert "async def _dir_source_pairs(" in src
        assert "def _dir_source_pairs(" in src and "async def _dir_source_pairs(" in src

    def test_dir_source_pairs_not_plain_sync_def(self) -> None:
        src = load()
        assert "\ndef _dir_source_pairs(" not in src

    def test_awaits_to_thread_for_get_all_playbook_dirs(self) -> None:
        src = load()
        assert "await asyncio.to_thread(get_all_playbook_dirs, sources_json, _PLAYBOOKS_DIR)" in src

    def test_no_direct_unwrapped_call(self) -> None:
        """get_all_playbook_dirs must never be called directly (unwrapped) in the sync path."""
        src = load()
        assert "= get_all_playbook_dirs(sources_json, _PLAYBOOKS_DIR)" not in src


class TestCallersAwaitDirSourcePairs:
    def test_list_library_awaits(self) -> None:
        src = load()
        assert "for d, source_key, source_label in await _dir_source_pairs(sources_json):" in src

    def test_enable_source_entries_awaits(self) -> None:
        src = load()
        assert "for d, sk, sl in await _dir_source_pairs(sources_json):" in src

    def test_no_unawaited_call_sites_remain(self) -> None:
        """Every call to _dir_source_pairs( in this file must be preceded by 'await '."""
        src = load()
        lines = [
            line
            for line in src.splitlines()
            if "_dir_source_pairs(" in line and "def _dir_source_pairs" not in line
        ]
        assert lines, "expected at least one call site of _dir_source_pairs"
        for line in lines:
            assert "await _dir_source_pairs(" in line, f"call site not awaited: {line!r}"
