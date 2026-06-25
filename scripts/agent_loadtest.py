#!/usr/bin/env python3
"""Manual load test for the in-handler agent SSE endpoint (ADR 0001 / #880).

This is a **standalone diagnostic tool**, not part of the test suite and not
imported by the app. It fires N concurrent requests at
``POST /api/v1/agent/run/stream``, reads each SSE stream to completion, and
reports p50/p95/max wall time plus the maximum number of runs observed in
flight at once. Use it to compare real numbers against the revisit triggers in
``docs/adr/0001-agent-execution-model.md`` before considering a rebuild.

Dependencies: stdlib + httpx (already a project dependency). No new deps.

Example:
    python scripts/agent_loadtest.py \\
        --base-url https://kri.local --token "$KRI_TOKEN" \\
        --concurrency 12 --total 60 --prompt "why is mm7 degraded?"

Notes:
- Respect the server's ``6/minute`` rate limit: a single token will get HTTP 429
  past 6 starts/minute. To exercise real concurrency, either raise the limit in a
  test environment or pass multiple tokens via --token-file (one JWT per line).
- The script never mutates the fleet; it only drives read-only agent turns. Avoid
  prompts that would propose live actions if you don't want approval rows created.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from dataclasses import dataclass

try:
    import httpx
except ImportError:  # pragma: no cover - manual tool
    sys.exit("httpx is required (it is already a project dependency): pip install httpx")

ENDPOINT = "/api/v1/agent/run/stream"


@dataclass
class RunResult:
    ok: bool
    status_code: int
    wall_s: float
    frames: int
    terminal: str | None
    error: str | None = None


class InFlight:
    """Tracks concurrent in-flight runs and the peak observed."""

    def __init__(self) -> None:
        self.current = 0
        self.peak = 0
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "InFlight":
        async with self._lock:
            self.current += 1
            self.peak = max(self.peak, self.current)
        return self

    async def __aexit__(self, *exc: object) -> None:
        async with self._lock:
            self.current -= 1


async def _one_run(
    client: httpx.AsyncClient,
    url: str,
    token: str,
    prompt: str,
    endpoint_id: str | None,
    inflight: InFlight,
) -> RunResult:
    headers = {"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}
    body: dict = {"prompt": prompt}
    if endpoint_id:
        body["endpoint_id"] = endpoint_id

    t0 = time.perf_counter()
    frames = 0
    terminal: str | None = None
    async with inflight:
        try:
            async with client.stream("POST", url, json=body, headers=headers) as resp:
                if resp.status_code != 200:
                    text = (await resp.aread()).decode(errors="replace")[:200]
                    return RunResult(
                        ok=False,
                        status_code=resp.status_code,
                        wall_s=time.perf_counter() - t0,
                        frames=0,
                        terminal=None,
                        error=text,
                    )
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    frames += 1
                    payload = line[len("data:") :].strip()
                    if payload == "[DONE]":
                        break
                    if '"type": "done"' in payload or '"type":"done"' in payload:
                        terminal = "done"
        except Exception as exc:  # noqa: BLE001 - report, don't crash the run
            return RunResult(
                ok=False,
                status_code=0,
                wall_s=time.perf_counter() - t0,
                frames=frames,
                terminal=terminal,
                error=repr(exc),
            )

    return RunResult(
        ok=True,
        status_code=200,
        wall_s=time.perf_counter() - t0,
        frames=frames,
        terminal=terminal,
    )


async def _run_all(args: argparse.Namespace, tokens: list[str]) -> list[RunResult]:
    url = args.base_url.rstrip("/") + ENDPOINT
    inflight = InFlight()
    sem = asyncio.Semaphore(args.concurrency)
    results: list[RunResult] = []

    limits = httpx.Limits(max_connections=args.concurrency + 5, max_keepalive_connections=args.concurrency)
    timeout = httpx.Timeout(args.timeout, read=args.timeout)
    async with httpx.AsyncClient(verify=not args.insecure, limits=limits, timeout=timeout) as client:

        async def worker(i: int) -> None:
            token = tokens[i % len(tokens)]
            async with sem:
                results.append(await _one_run(client, url, token, args.prompt, args.endpoint_id, inflight))

        await asyncio.gather(*(worker(i) for i in range(args.total)))

    print(f"\nmax in-flight observed: {inflight.peak}")
    return results


def _report(results: list[RunResult]) -> int:
    oks = [r for r in results if r.ok]
    fails = [r for r in results if not r.ok]
    waltimes = sorted(r.wall_s for r in oks)

    print("\n=== agent load-test report ===")
    print(f"total runs       : {len(results)}")
    print(f"successful (200) : {len(oks)}")
    print(f"failed           : {len(fails)}")

    if waltimes:
        p50 = statistics.median(waltimes)
        p95 = waltimes[min(len(waltimes) - 1, int(round(0.95 * (len(waltimes) - 1))))]
        print(f"wall time p50    : {p50:.2f}s")
        print(f"wall time p95    : {p95:.2f}s")
        print(f"wall time max    : {max(waltimes):.2f}s")
        print(f"wall time mean   : {statistics.fmean(waltimes):.2f}s")

    if fails:
        codes: dict[int, int] = {}
        for r in fails:
            codes[r.status_code] = codes.get(r.status_code, 0) + 1
        print(f"failure codes    : {codes}")
        sample = next((r for r in fails if r.error), None)
        if sample:
            print(f"sample error     : {sample.error}")

    print("\nCompare against ADR 0001 revisit triggers:")
    print("  - peak in-flight >= 8/replica, or any DB pool_timeout in API logs")
    print("  - p95 wall time  >= 45s on the local-MLX planner tier")
    return 1 if fails else 0


def _load_tokens(args: argparse.Namespace) -> list[str]:
    if args.token_file:
        with open(args.token_file, encoding="utf-8") as fh:
            tokens = [ln.strip() for ln in fh if ln.strip()]
        if not tokens:
            sys.exit("--token-file is empty")
        return tokens
    if args.token:
        return [args.token]
    sys.exit("provide --token or --token-file (a valid operator/admin JWT)")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-url", required=True, help="e.g. https://kri.local")
    p.add_argument("--token", help="operator/admin bearer JWT")
    p.add_argument("--token-file", help="file with one JWT per line (to spread past the per-user rate limit)")
    p.add_argument("--prompt", default="why is mm7 degraded?", help="agent prompt (keep it read-only)")
    p.add_argument("--endpoint-id", default=None, help="optional LLM endpoint UUID; omit to use the tier router")
    p.add_argument("--concurrency", type=int, default=8, help="max simultaneous in-flight runs")
    p.add_argument("--total", type=int, default=24, help="total runs to issue")
    p.add_argument("--timeout", type=float, default=120.0, help="per-run read timeout (s)")
    p.add_argument("--insecure", action="store_true", help="skip TLS verification (self-signed dev certs)")
    args = p.parse_args()

    tokens = _load_tokens(args)
    print(f"firing {args.total} runs at concurrency {args.concurrency} against {args.base_url}{ENDPOINT}")
    results = asyncio.run(_run_all(args, tokens))
    return _report(results)


if __name__ == "__main__":
    raise SystemExit(main())
