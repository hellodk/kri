"""#990 — salt-api calls in salt_keys must not block the async event loop.

list_keys is polled constantly (notification badge). Its run_wheel call does a
SYNCHRONOUS requests.post; when salt-api is unreachable it timed out for 10s
INSIDE the async endpoint, freezing the whole event loop and stalling every
concurrent request (nodes/overview/masters). Every blocking salt-api call in an
async route must go through asyncio.to_thread.
"""

from pathlib import Path

_SRC = (
    Path(__file__).resolve().parents[2] / "fleet_platform" / "api" / "routes" / "salt_keys.py"
).read_text()


def test_run_wheel_only_via_to_thread():
    # A bare `run_wheel(` call is the blocking bug. Every use must be
    # `asyncio.to_thread(run_wheel, ...)` (which reads as `run_wheel,` — no paren).
    assert "run_wheel(" not in _SRC, "run_wheel (blocking) must only be called via asyncio.to_thread"
    assert _SRC.count("to_thread(run_wheel") == 4, "all four key ops must be to_thread-wrapped"


def test_salt_api_timeout_is_low():
    api = (
        Path(__file__).resolve().parents[2] / "fleet_platform" / "services" / "salt_api_client.py"
    ).read_text()
    import re

    m = re.search(r"_API_TIMEOUT = (\d+)", api)
    assert m and int(m.group(1)) <= 5, "salt-api timeout should be low (blocking probe runs in a thread)"
