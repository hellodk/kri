"""Source-contract tests for #1005 A4: group/node pillar writes must not block the event loop.

group_secrets_svc.write_group_pillar/rebuild_top_sls and node_secrets_svc.write_node_pillar
are `async def` but previously performed a blocking `open()` + `fcntl.flock()` write directly
in the coroutine. This freezes the whole event loop while the lock is held/write happens. The
fix moves the blocking body into a sync helper invoked via `asyncio.to_thread(...)`.
"""

from pathlib import Path

GROUP_SECRETS_SVC_PATH = Path(__file__).parent.parent.parent / "fleet_platform/services/group_secrets_svc.py"
NODE_SECRETS_SVC_PATH = Path(__file__).parent.parent.parent / "fleet_platform/services/node_secrets_svc.py"


def load(path: Path) -> str:
    return path.read_text()


class TestGroupSecretsSvcAsyncOffload:
    def test_imports_asyncio(self) -> None:
        src = load(GROUP_SECRETS_SVC_PATH)
        assert "import asyncio" in src

    def test_write_group_pillar_uses_to_thread(self) -> None:
        src = load(GROUP_SECRETS_SVC_PATH)
        assert "async def write_group_pillar" in src
        assert "await asyncio.to_thread(_write_group_pillar_sync" in src

    def test_rebuild_top_sls_uses_to_thread(self) -> None:
        src = load(GROUP_SECRETS_SVC_PATH)
        assert "async def rebuild_top_sls" in src
        assert "await asyncio.to_thread(_write_top_sls_sync" in src

    def test_sync_helpers_hold_the_flock(self) -> None:
        src = load(GROUP_SECRETS_SVC_PATH)
        assert "def _write_group_pillar_sync(" in src
        assert "def _write_top_sls_sync(" in src
        assert "fcntl.flock" in src

    def test_no_blocking_flock_call_inside_async_def_body(self) -> None:
        """The async coroutines themselves must not directly *call* fcntl.flock (comments OK)."""
        src = load(GROUP_SECRETS_SVC_PATH)
        write_group_pillar_body = src.split("async def write_group_pillar")[1].split("async def rebuild_top_sls")[0]
        assert "fcntl.flock(" not in write_group_pillar_body

        rebuild_top_sls_body = src.split("async def rebuild_top_sls")[1].split("def _write_top_sls_sync")[0]
        assert "fcntl.flock(" not in rebuild_top_sls_body


class TestNodeSecretsSvcAsyncOffload:
    def test_imports_asyncio(self) -> None:
        src = load(NODE_SECRETS_SVC_PATH)
        assert "import asyncio" in src

    def test_write_node_pillar_uses_to_thread(self) -> None:
        src = load(NODE_SECRETS_SVC_PATH)
        assert "async def write_node_pillar" in src
        assert "await asyncio.to_thread(_write_node_pillar_sync" in src

    def test_sync_helper_holds_the_flock(self) -> None:
        src = load(NODE_SECRETS_SVC_PATH)
        assert "def _write_node_pillar_sync(" in src
        assert "fcntl.flock" in src

    def test_no_blocking_flock_call_inside_async_def_body(self) -> None:
        """The async coroutine itself must not directly *call* fcntl.flock (comments OK)."""
        src = load(NODE_SECRETS_SVC_PATH)
        write_node_pillar_body = src.split("async def write_node_pillar")[1]
        assert "fcntl.flock(" not in write_node_pillar_body
