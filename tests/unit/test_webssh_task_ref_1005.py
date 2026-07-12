"""Source-contract tests for #1005 A5: webssh SSH-stdout pump task must be referenced.

`asyncio.create_task(read_ssh())` with no stored reference means asyncio only holds a
weak ref to the Task — it can be garbage-collected mid-session, silently killing
terminal output. The fix stores the Task on the session-lifetime `proxy` object
(SSHProxySession._read_task) and attaches a done-callback, following the
ws_task/vnc_task pattern in vnc.py:258-259.
"""

from pathlib import Path

WEBSSH_PATH = Path(__file__).parent.parent.parent / "fleet_platform/api/routes/webssh.py"


def load() -> str:
    return WEBSSH_PATH.read_text()


class TestWebsshReadTaskReference:
    def test_no_bare_unassigned_create_task_for_read_ssh(self) -> None:
        """The old `asyncio.create_task(read_ssh())` statement (no assignment) must be gone."""
        src = load()
        bare_lines = [line for line in src.splitlines() if line.strip() == "asyncio.create_task(read_ssh())"]
        assert bare_lines == []

    def test_read_task_stored_on_proxy(self) -> None:
        src = load()
        assert "proxy._read_task = asyncio.create_task(read_ssh())" in src

    def test_read_task_attribute_initialized_in_session(self) -> None:
        src = load()
        assert "self._read_task: asyncio.Task | None = None" in src

    def test_done_callback_attached(self) -> None:
        src = load()
        assert "add_done_callback" in src
        assert "proxy._read_task.add_done_callback(_read_task_done)" in src

    def test_close_cancels_pending_read_task(self) -> None:
        """close() should cancel the pump task if the session ends before it finishes."""
        src = load()
        close_body = src.split("async def close(self")[1]
        assert "self._read_task" in close_body
        assert ".cancel()" in close_body
