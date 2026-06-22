#!/usr/bin/env python3
"""MLX tier benchmark harness (#712).

Measures, per OpenAI-compatible endpoint: p50/p95 first-token latency and a
tool-call accuracy rate against a small fixed prompt set. Used to validate the
local cluster meets the Phase-C gate (p95 first-token <= 2.5 s on planners,
>= ~88% tool-call accuracy) before rolling out to all 18 minis.

Usage:
    python scripts/mlx_bench.py --base-url http://mm1:8080/v1 --model qwen2.5-14b \\
        --tier planner --runs 20

No kri imports — pure stdlib + requests so it can run from a laptop against the
fleet. Exits non-zero if a configured gate is missed.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request

# Prompts that should elicit exactly one JSON tool call (prompt-embedded mode).
_TOOL_PROMPTS = [
    "You can call tools. To call one reply with a single JSON object "
    '{"name": "...", "arguments": {...}} and nothing else. '
    "Tool: get_node(identifier). Question: show me node mm7.",
    'You can call tools. Reply with one JSON object {"name","arguments"} only. '
    "Tool: list_nodes(status). Question: which nodes are degraded?",
    'You can call tools. Reply with one JSON object {"name","arguments"} only. '
    "Tool: ping_node(minion_id). Question: is mm3 reachable?",
]

_GATES = {
    "planner": {"p95_first_token_s": 2.5, "tool_accuracy": 0.88},
    "coder": {"p95_first_token_s": 4.0, "tool_accuracy": 0.85},
    "worker": {"p95_first_token_s": 2.0, "tool_accuracy": 0.80},
    "embed": {"p95_first_token_s": 1.0, "tool_accuracy": 0.0},
}


def _post(base_url: str, model: str, prompt: str, timeout: float) -> tuple[float, str]:
    """Return (first_token_seconds, full_text). Uses streaming to time first token."""
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "max_tokens": 128,
            "temperature": 0.0,
        }
    ).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    t0 = time.perf_counter()
    first_token_at: float | None = None
    chunks: list[str] = []
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — operator-supplied URL
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[len("data:") :].strip()
            if payload == "[DONE]":
                break
            try:
                delta = json.loads(payload)["choices"][0]["delta"].get("content", "")
            except (json.JSONDecodeError, KeyError, IndexError):
                continue
            if delta:
                if first_token_at is None:
                    first_token_at = time.perf_counter() - t0
                chunks.append(delta)
    return (first_token_at if first_token_at is not None else timeout, "".join(chunks))


def _looks_like_tool_call(text: str) -> bool:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return False
    try:
        obj = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return False
    return isinstance(obj, dict) and "name" in obj and "arguments" in obj


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True, help="OpenAI-compatible base, e.g. http://mm1:8080/v1")
    ap.add_argument("--model", required=True)
    ap.add_argument("--tier", choices=sorted(_GATES), default="worker")
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--timeout", type=float, default=30.0)
    args = ap.parse_args()

    first_tokens: list[float] = []
    tool_hits = 0
    tool_total = 0
    errors = 0

    for i in range(args.runs):
        prompt = _TOOL_PROMPTS[i % len(_TOOL_PROMPTS)]
        try:
            ftl, text = _post(args.base_url, args.model, prompt, args.timeout)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            errors += 1
            print(f"  run {i + 1}: ERROR {exc}", file=sys.stderr)
            continue
        first_tokens.append(ftl)
        if args.tier != "embed":
            tool_total += 1
            if _looks_like_tool_call(text):
                tool_hits += 1

    if not first_tokens:
        print("All runs failed — endpoint unreachable.", file=sys.stderr)
        return 2

    first_tokens.sort()
    p50 = statistics.median(first_tokens)
    idx95 = max(0, int(len(first_tokens) * 0.95) - 1)
    p95 = first_tokens[idx95]
    accuracy = (tool_hits / tool_total) if tool_total else 1.0

    gate = _GATES[args.tier]
    print(
        json.dumps(
            {
                "tier": args.tier,
                "model": args.model,
                "runs": args.runs,
                "errors": errors,
                "p50_first_token_s": round(p50, 3),
                "p95_first_token_s": round(p95, 3),
                "tool_accuracy": round(accuracy, 3),
                "gate": gate,
            },
            indent=2,
        )
    )

    ok = p95 <= gate["p95_first_token_s"] and accuracy >= gate["tool_accuracy"]
    print(("PASS" if ok else "FAIL") + f" — tier '{args.tier}' gate")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
