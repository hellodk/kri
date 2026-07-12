"""Issue #991 A1 — salt_master_probe.run_probe must not freeze the event loop.

`run_probe` is awaited from an async FastAPI route (`test_salt_master`) wrapped in
`asyncio.wait_for(..., 30)`. Its body is 100% synchronous network I/O (socket +
requests.post ×4), so a coroutine that never awaits cannot be cancelled by
`wait_for` — the whole event loop freezes for 50s+. The fix offloads the blocking
body to a worker thread via `asyncio.to_thread`, so the loop yields and the
timeout can actually fire.

Run: pytest tests/unit/test_run_probe_nonblocking_991.py -q
"""

from pathlib import Path

_SRC = (Path(__file__).resolve().parents[2] / "fleet_platform" / "services" / "salt_master_probe.py").read_text()


# ── source-contract: the blocking body is offloaded to a thread ──────────────


def test_run_probe_offloads_to_thread():
    assert "asyncio.to_thread(" in _SRC, (
        "run_probe must offload its synchronous body via asyncio.to_thread so "
        "the FastAPI event loop is not frozen during the probe (#991 A1)."
    )


def test_sync_probe_helper_exists():
    assert "def _run_probe_sync(" in _SRC, (
        "the synchronous probe body must live in a plain `def _run_probe_sync` "
        "that run_probe hands to asyncio.to_thread (#991 A1)."
    )


def test_run_probe_body_no_longer_inlines_blocking_checks():
    """run_probe itself must be a thin async wrapper — the blocking `_check_*`
    calls belong to the sync helper, not the coroutine body."""
    lines = _SRC.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("async def run_probe("))
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("def _run_probe_sync("))
    body = "\n".join(lines[start:end])
    assert "_check_dns(" not in body, (
        "run_probe must delegate to _run_probe_sync via to_thread, not call the "
        "blocking _check_* helpers directly in the coroutine body (#991 A1)."
    )


# ── behavioral: run_probe still returns a valid ProbeResult ──────────────────


async def test_run_probe_still_returns_probe_result(monkeypatch):
    """Offloading to a thread must not change the return contract."""
    import fleet_platform.services.salt_master_probe as smp

    master = type(
        "M",
        (),
        {
            "api_password_enc": "",
            "api_url": "",
            "api_user": "",
            "api_eauth": "pam",
            "tls_verify": False,
            "address": "192.168.1.50",
            "publish_port": 4505,
            "ret_port": 4506,
        },
    )()

    # Stub every blocking check so the thread does no real I/O.
    ok = {"check": "x", "status": "pass", "detail": "", "latency_ms": 0}
    for fn in (
        "_check_dns",
        "_check_tcp",
        "_check_token_delivery",
    ):
        monkeypatch.setattr(smp, fn, lambda *a, **k: dict(ok))
    monkeypatch.setattr(smp, "_aggregate", lambda checks: "healthy")

    result = await smp.run_probe(master)
    assert result["status"] == "healthy"
    assert isinstance(result["checks"], list)
