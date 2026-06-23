"""Regression tests for issue #740: asyncio.get_running_loop() inside coroutines."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

TARGETS = {
    "fleet_platform/api/routes/webssh.py": "get_running_loop()",
    "fleet_platform/api/routes/nodes.py": "get_running_loop()",
    "fleet_platform/api/routes/platform_settings.py": "_asyncio.get_running_loop()",
}


def test_no_get_event_loop_in_target_files():
    """Target route files must use get_running_loop(), not deprecated get_event_loop()."""
    for rel_path, expected_substring in TARGETS.items():
        source = (REPO_ROOT / rel_path).read_text()
        assert source.count("get_event_loop(") == 0, (
            f"{rel_path} still contains get_event_loop() — use get_running_loop() inside async def"
        )
        assert expected_substring in source, f"{rel_path} must contain {expected_substring!r}"
