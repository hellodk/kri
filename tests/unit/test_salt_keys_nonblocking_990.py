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


def test_run_wheel_never_called_bare_in_async_routes():
    # No bare `run_wheel(` call — every one is wrapped in asyncio.to_thread(run_wheel, ...).
    import re

    bare = re.findall(r"(?<!to_thread\()\brun_wheel\(", _SRC)
    # The import line `import ... run_wheel` is not a call; only calls end with '('.
    calls = [m for m in re.findall(r"\brun_wheel\(", _SRC)]
    wrapped = _SRC.count("to_thread(run_wheel")
    assert wrapped == len(calls), f"all run_wheel calls must be to_thread-wrapped: {wrapped}/{len(calls)}"


def test_salt_api_timeout_is_low():
    api = (
        Path(__file__).resolve().parents[2] / "fleet_platform" / "services" / "salt_api_client.py"
    ).read_text()
    import re

    m = re.search(r"_API_TIMEOUT = (\d+)", api)
    assert m and int(m.group(1)) <= 5, "salt-api timeout should be low (blocking probe runs in a thread)"
