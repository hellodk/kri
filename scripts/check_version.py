#!/usr/bin/env python3
"""
Verify that the version chain is consistent.

Single source of truth: VERSION file.
Everything else must read from it — never store a copy.

Usage:
    python3 scripts/check_version.py
    ./scripts/kri.sh version   (if wired up)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
VERSION_FILE = ROOT / "VERSION"

errors: list[str] = []
warnings: list[str] = []


def check(label: str, actual: str, expected: str, is_error: bool = True) -> None:
    if actual == expected:
        print(f"  ✓ {label}: {actual}")
    else:
        msg = f"  {'✗' if is_error else '⚠'} {label}: got {actual!r}, expected {expected!r}"
        print(msg)
        (errors if is_error else warnings).append(msg)


# ── Read canonical version ──────────────────────────────────────────────────
if not VERSION_FILE.exists():
    print("ERROR: VERSION file not found")
    sys.exit(1)

canonical = VERSION_FILE.read_text().strip()
print(f"\nCanonical version (VERSION file): {canonical}\n")

# ── pyproject.toml ──────────────────────────────────────────────────────────
try:
    import tomllib
    d = tomllib.load(open(ROOT / "pyproject.toml", "rb"))
    proj = d.get("project", {})
    if "version" in proj:
        errors.append("  ✗ pyproject.toml has hardcoded 'version' — remove it, use dynamic")
        print(f"  ✗ pyproject.toml: hardcoded version={proj['version']!r} (should use dynamic)")
    elif "version" in d.get("tool", {}).get("setuptools", {}).get("dynamic", {}):
        dyn = d["tool"]["setuptools"]["dynamic"]["version"]
        if dyn.get("file") == "VERSION":
            print("  ✓ pyproject.toml: dynamic version from VERSION file")
        else:
            errors.append(f"  ✗ pyproject.toml dynamic version file is {dyn!r}, expected VERSION")
    else:
        warnings.append("  ⚠ pyproject.toml: no version field and no dynamic config found")
        print("  ⚠ pyproject.toml: version not configured")
except Exception as e:
    warnings.append(f"  ⚠ pyproject.toml: could not parse ({e})")

# ── package.json ────────────────────────────────────────────────────────────
try:
    import json
    pkg = json.loads((ROOT / "frontend" / "package.json").read_text())
    v = pkg.get("version", "(missing)")
    if v == "0.0.0":
        print("  ✓ package.json: 0.0.0 placeholder (correct — not a source of truth)")
    else:
        errors.append(f"  ✗ package.json has version={v!r} — reset to 0.0.0")
        print(f"  ✗ package.json: {v!r} (should be 0.0.0 placeholder)")
except Exception as e:
    warnings.append(f"  ⚠ package.json: could not parse ({e})")

# ── Backend config.py reads from file ───────────────────────────────────────
try:
    src = (ROOT / "fleet_platform" / "core" / "config.py").read_text()
    if "_read_version" in src and "VERSION" in src:
        print("  ✓ config.py: reads version from VERSION file")
    else:
        errors.append("  ✗ config.py: does not read from VERSION file")
        print("  ✗ config.py: missing dynamic VERSION read")
except Exception as e:
    warnings.append(f"  ⚠ config.py: could not read ({e})")

# ── vite.config.ts reads from file ──────────────────────────────────────────
try:
    src = (ROOT / "frontend" / "vite.config.ts").read_text()
    if "readVersion" in src and "VERSION" in src:
        print("  ✓ vite.config.ts: reads version from VERSION file")
    else:
        errors.append("  ✗ vite.config.ts: does not read from VERSION file")
        print("  ✗ vite.config.ts: missing dynamic VERSION read")
except Exception as e:
    warnings.append(f"  ⚠ vite.config.ts: could not read ({e})")

# ── .githooks/pre-commit ─────────────────────────────────────────────────────
try:
    hook = (ROOT / ".githooks" / "pre-commit").read_text()
    # Check for actual write commands (not just comment mentions)
    active_lines = [l for l in hook.splitlines() if not l.strip().startswith("#")]
    active = "\n".join(active_lines)
    if ("sed -i" in active and "pyproject" in active) or ("package.json" in active and "write" in active.lower()):
        errors.append("  ✗ pre-commit hook still writes to pyproject.toml or package.json")
        print("  ✗ pre-commit hook: still has pyproject/package.json write (remove it)")
    else:
        print("  ✓ pre-commit hook: only updates VERSION file")
except Exception as e:
    warnings.append(f"  ⚠ .githooks/pre-commit: could not read ({e})")

# ── Summary ──────────────────────────────────────────────────────────────────
print()
if errors:
    print(f"FAIL — {len(errors)} error(s):")
    for e in errors: print(f"  {e}")
    sys.exit(1)
elif warnings:
    print(f"PASS with {len(warnings)} warning(s):")
    for w in warnings: print(f"  {w}")
else:
    print("PASS — version chain is consistent. Single source of truth: VERSION")
