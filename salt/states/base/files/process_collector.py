"""
kri node-side process telemetry collector.

Collects per-process stats via psutil and posts them to the Fleet Platform
ingest API at POST /api/v1/ingest/process_stats.

Dependencies: psutil (installed by process_report.sls before this script runs).
stdlib-only aside from psutil; psutil is imported lazily inside collect() so
the pure classifier (is_llm_process) is importable without psutil present.

Usage (invoked by process_report.sls):
    INGEST_URL=https://... NODE_TOKEN=... MINION_ID=<id> python3 process_collector.py
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# LLM / AI runtime patterns
# ---------------------------------------------------------------------------

_LLM_PATTERNS = (
    "exo",
    "mlx",
    "llama",
    "vllm",
    "ollama",
    "llm",
    "tinygrad",
    "model-server",
    "model_server",
    "modelserver",
    "text-generation",
    "text_generation",
    "triton",
    "torchserve",
    "torchserve",
    "bentoml",
    "ray",
)

_SYSTEM_PROCS = frozenset(
    {
        "sshd",
        "salt-minion",
        "salt-master",
        "kernel_task",
        "launchd",
        "WindowServer",
        "systemd",
        "kthreadd",
        "init",
        "loginwindow",
        "com.apple.security",
        "com.apple.cfnetwork",
    }
)


def is_llm_process(name: str, cmdline: str) -> bool:
    """Return True if this process appears to be an LLM/AI runtime.

    Checks both name and cmdline case-insensitively against known LLM
    runtime patterns.  Known system procs always return False.

    Args:
        name: process name (e.g. from psutil proc.name())
        cmdline: full command line string (e.g. " ".join(proc.cmdline()))

    Returns:
        True if the process matches an LLM runtime pattern.
    """
    name_lower = (name or "").lower()
    cmdline_lower = (cmdline or "").lower()

    # Fast-exit for known system processes
    if name_lower in {p.lower() for p in _SYSTEM_PROCS}:
        return False

    for pattern in _LLM_PATTERNS:
        if pattern in name_lower or pattern in cmdline_lower:
            return True

    return False


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


def collect(top_n: int = 200) -> list[dict]:
    """Collect per-process stats using psutil.

    psutil is imported inside this function so the module remains importable
    in environments where psutil is not installed (unit tests need only
    is_llm_process).

    Guards each per-process access with try/except to handle transient
    NoSuchProcess / AccessDenied errors (common on macOS for system procs).

    IO counters may be None on macOS (requires root); they are included as
    None in the output in that case.

    Args:
        top_n: maximum number of processes to return, sorted by mem_rss_bytes
               descending. The ingest endpoint caps at 250; default 200
               leaves headroom.

    Returns:
        List of process dicts ready for the ingest payload.
    """
    import psutil  # noqa: PLC0415 — lazy import intentional

    procs: list[dict] = []
    for proc in psutil.process_iter(
        [
            "pid",
            "name",
            "cmdline",
            "cpu_percent",
            "memory_info",
            "memory_percent",
            "num_threads",
            "status",
            "username",
        ]
    ):
        try:
            info = proc.info
            name: str = info.get("name") or ""
            cmdline_list: list[str] = info.get("cmdline") or []
            cmdline: str = " ".join(cmdline_list)

            mem_info = info.get("memory_info")
            mem_rss: int = mem_info.rss if mem_info else 0

            # IO counters — may raise AccessDenied or return None on macOS
            try:
                io = proc.io_counters()
                io_read: int | None = io.read_bytes if io else None
                io_write: int | None = io.write_bytes if io else None
            except (psutil.AccessDenied, AttributeError, NotImplementedError):
                io_read = None
                io_write = None

            procs.append(
                {
                    "pid": info.get("pid"),
                    "name": name,
                    "cmdline": cmdline,
                    "cpu_pct": info.get("cpu_percent") or 0.0,
                    "mem_rss_bytes": mem_rss,
                    "mem_pct": info.get("memory_percent") or 0.0,
                    "num_threads": info.get("num_threads") or 0,
                    "status": info.get("status") or "",
                    "username": info.get("username") or "",
                    "io_read_bytes": io_read,
                    "io_write_bytes": io_write,
                    "is_llm": is_llm_process(name, cmdline),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    procs.sort(key=lambda p: p["mem_rss_bytes"], reverse=True)
    return procs[:top_n]


# ---------------------------------------------------------------------------
# Poster
# ---------------------------------------------------------------------------


def post(
    ingest_url: str,
    node_token: str,
    minion_id: str,
    processes: list[dict],
) -> int:
    """POST the process stats payload to the Fleet Platform ingest endpoint.

    Uses stdlib urllib.request only (no third-party HTTP library required).

    Args:
        ingest_url: base URL of the ingest API (e.g. https://kri.local/api/v1/ingest)
        node_token: value for the X-Node-Token header
        minion_id: Salt minion ID for this node
        processes: list of process dicts from collect()

    Returns:
        HTTP status code from the response.
    """
    payload = json.dumps(
        {
            "minion_id": minion_id,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "processes": processes,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        f"{ingest_url}/process_stats",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Node-Token": node_token,
        },
        method="POST",
    )

    resp = urllib.request.urlopen(req, timeout=30)
    return resp.status


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Read config from env / argv, collect and post process stats."""
    ingest_url = os.environ.get("INGEST_URL", "").rstrip("/")
    node_token = os.environ.get("NODE_TOKEN", "")
    minion_id = os.environ.get("MINION_ID", "")

    if not ingest_url:
        print("[process_collector] INGEST_URL not set — exiting", file=sys.stderr)
        sys.exit(1)
    if not minion_id:
        print("[process_collector] MINION_ID not set — exiting", file=sys.stderr)
        sys.exit(1)

    try:
        procs = collect()
    except Exception as exc:
        print(f"[process_collector] collection failed: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        status = post(ingest_url, node_token, minion_id, procs)
        print(f"[process_collector] posted {len(procs)} processes → HTTP {status}")
    except Exception as exc:
        print(f"[process_collector] ingest POST failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
