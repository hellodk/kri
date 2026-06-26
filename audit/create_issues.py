#!/usr/bin/env python3
"""Create one GitHub issue per audit finding. Idempotent: re-running skips
findings already present in issues_map.json. Writes id -> {number,url,title}."""
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from findings_data import FINDINGS

_map_lock = threading.Lock()

REPO = "hellodk/kri"
HERE = os.path.dirname(os.path.abspath(__file__))
MAP_PATH = os.path.join(HERE, "issues_map.json")

SEV_LABEL = {
    "Critical": "p0-critical",
    "High": "p1-high",
    "Medium": "p2-normal",
    "Low": "p3-low",
}


def load_map() -> dict:
    if os.path.exists(MAP_PATH):
        with open(MAP_PATH) as fh:
            return json.load(fh)
    return {}


def save_map(m: dict) -> None:
    with open(MAP_PATH, "w") as fh:
        json.dump(m, fh, indent=2)


def body_for(f: dict) -> str:
    return f"""> Auto-filed by the external multi-persona audit (2026-06). **Do not fix until reviewed.**

**Auditor persona:** {f['persona']}
**Severity:** {f['severity']}
**Finding ID:** `{f['id']}`

### Location
`{f['location']}`

### Evidence
```
{f['evidence']}
```

### Impact
{f['impact']}

### Recommended fix
{f['recommendation']}

---
<sub>Tracked in the audit report. Labels: severity = `{SEV_LABEL[f['severity']]}`.</sub>
"""


def labels_for(f: dict) -> list[str]:
    out = ["audit", SEV_LABEL[f["severity"]]]
    for lbl in f.get("labels", []):
        if lbl not in out:
            out.append(lbl)
    return out


def create_issue(f: dict) -> dict:
    title = f"[Audit] {f['title']} ({f['id']})"
    cmd = [
        "gh", "issue", "create",
        "--repo", REPO,
        "--title", title,
        "--body", body_for(f),
    ]
    for lbl in labels_for(f):
        cmd += ["--label", lbl]
    last_err = ""
    for attempt in range(5):
        res = subprocess.run(cmd, capture_output=True, text=True)
        lines = [ln for ln in res.stdout.strip().splitlines() if "github.com" in ln]
        if res.returncode == 0 and lines:
            url = lines[-1]
            number = url.rstrip("/").split("/")[-1]
            return {"number": int(number), "url": url, "title": title}
        last_err = (res.stderr.strip() or res.stdout.strip() or "empty output")[:200]
        # secondary rate limit / transient -> backoff
        time.sleep(2 ** attempt + 1)
    raise RuntimeError(f"gh failed for {f['id']}: {last_err}")


def _work(f: dict, m: dict) -> str:
    info = create_issue(f)
    with _map_lock:
        m[f["id"]] = info
        save_map(m)
    return f"  {f['id']:<7} -> #{info['number']}  {f['title'][:60]}"


def main() -> None:
    only = set(sys.argv[1:])  # optional: restrict to specific finding ids
    m = load_map()
    todo = [f for f in FINDINGS if (not only or f["id"] in only) and f["id"] not in m]
    workers = int(os.environ.get("AUDIT_WORKERS", "6"))
    created = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_work, f, m): f for f in todo}
        for fut in as_completed(futs):
            f = futs[fut]
            try:
                print(fut.result())
                created += 1
            except Exception as exc:  # noqa: BLE001
                print(f"  {f['id']:<7} -> FAILED: {exc}")
    print(f"Done. Created {created} new issues. Total mapped: {len(m)}.")


if __name__ == "__main__":
    main()
