"""Source-contract tests for async-event-loop-blocking fixes (#999).

Confirmed bug class (same as the merged salt_keys.py asyncio.to_thread fix):

A2 — ``get_all_playbook_dirs`` (fleet_platform/services/playbook_sources.py) is a
sync function that may git-clone (blocking subprocess.run with timeout=60). Every
call site that sits directly inside an ``async def`` FastAPI route handler must be
wrapped in ``await asyncio.to_thread(get_all_playbook_dirs, ...)``.

A3 — ``check_jenkins_agent`` (fleet_platform/services/ios_tracking_svc.py) is
``async def`` but previously called ``urllib.request.urlopen(..., timeout=5)``
directly on the event loop. The blocking call must be moved into a sync inner
function invoked via ``await asyncio.to_thread(...)``.

All paths are resolved relative to this file's location (never absolute), so the
tests work regardless of cwd.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Route files where every get_all_playbook_dirs() call site sits inside an
# `async def` handler and was wrapped in asyncio.to_thread.
WRAPPED_ROUTE_FILES = [
    REPO_ROOT / "fleet_platform" / "api" / "routes" / "ansible" / "playbooks.py",
    REPO_ROOT / "fleet_platform" / "api" / "routes" / "ansible" / "files.py",
    REPO_ROOT / "fleet_platform" / "api" / "routes" / "agent.py",
]

# Expected number of `get_all_playbook_dirs(` call sites (any form) per file —
# used to make sure every occurrence is the wrapped (to_thread) form, not just
# "at least one".
EXPECTED_CALL_COUNTS = {
    "playbooks.py": 3,
    "files.py": 2,
    "agent.py": 2,
}

IOS_TRACKING_SVC = REPO_ROOT / "fleet_platform" / "services" / "ios_tracking_svc.py"


def _text(path: Path) -> str:
    assert path.is_file(), f"expected file not found: {path}"
    return path.read_text()


def test_wrapped_route_files_exist():
    for path in WRAPPED_ROUTE_FILES:
        assert path.is_file(), f"missing expected route file: {path}"


def test_every_edited_route_file_imports_asyncio():
    for path in WRAPPED_ROUTE_FILES:
        text = _text(path)
        assert "import asyncio" in text, f"{path} missing 'import asyncio'"


def test_every_edited_route_file_wraps_get_all_playbook_dirs():
    for path in WRAPPED_ROUTE_FILES:
        text = _text(path)
        assert "await asyncio.to_thread(get_all_playbook_dirs" in text, (
            f"{path} does not contain a to_thread-wrapped get_all_playbook_dirs call"
        )


def test_no_unwrapped_get_all_playbook_dirs_calls_remain():
    """A wrapped call looks like ``asyncio.to_thread(get_all_playbook_dirs, ...)``
    — the function name is passed *by reference*, so it is never immediately
    followed by its own '('. A bare, un-awaited call site (the old bug) always
    looks like ``get_all_playbook_dirs(...)``. Assert zero of the bare form
    remain in the fixed route files."""
    for path in WRAPPED_ROUTE_FILES:
        text = _text(path)
        bare_call_count = text.count("get_all_playbook_dirs(")
        assert bare_call_count == 0, (
            f"{path}: found {bare_call_count} un-awaited get_all_playbook_dirs( call(s)"
        )


def test_wrapped_call_count_matches_expected():
    for path in WRAPPED_ROUTE_FILES:
        text = _text(path)
        wrapped_count = text.count("asyncio.to_thread(get_all_playbook_dirs")
        expected = EXPECTED_CALL_COUNTS[path.name]
        assert wrapped_count == expected, (
            f"{path}: expected {expected} to_thread-wrapped call sites, found {wrapped_count}"
        )


def test_ios_tracking_svc_wraps_blocking_urlopen():
    text = _text(IOS_TRACKING_SVC)
    assert "import asyncio" in text
    assert "asyncio.to_thread(" in text


def test_ios_tracking_svc_check_jenkins_agent_still_async():
    text = _text(IOS_TRACKING_SVC)
    assert "async def check_jenkins_agent(" in text


def test_playbook_library_call_site_intentionally_not_wrapped():
    """fleet_platform/api/routes/playbook_library.py line ~64 sits inside the
    sync helper `_dir_source_pairs` (a plain `def`, not `async def`), so it
    cannot be awaited without first making that helper async — out of scope
    for this fix. Document that it remains unwrapped."""
    path = REPO_ROOT / "fleet_platform" / "api" / "routes" / "playbook_library.py"
    text = _text(path)
    assert "def _dir_source_pairs(" in text
    assert "async def _dir_source_pairs(" not in text
    assert "all_dirs = get_all_playbook_dirs(sources_json, _PLAYBOOKS_DIR)" in text
