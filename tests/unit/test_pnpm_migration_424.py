"""#424: kri uses pnpm, not npm — everywhere (global rule)."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
FILES = [
    ROOT / "deploy/Dockerfile.frontend",
    ROOT / "deploy/Dockerfile.frontend.dev",
    ROOT / ".pre-commit-config.yaml",
    ROOT / ".github/workflows/ci.yml",
]
PIN = "pnpm@10.29.3"


def test_no_npm_npx_yarn_anywhere():
    # word-boundary so 'pnpm run'/'pnpm install' don't false-match 'npm run' etc.
    bad = [r"\bnpm ci\b", r"\bnpm run\b", r"\bnpm install\b", r"\bnpx ", r"\byarn "]
    for f in FILES:
        text = f.read_text()
        for pat in bad:
            assert not re.search(pat, text), f"{f.name} still references {pat!r}"


def test_lockfiles():
    assert not (ROOT / "frontend/package-lock.json").exists(), "package-lock.json must be removed"
    assert (ROOT / "frontend/pnpm-lock.yaml").exists(), "pnpm-lock.yaml must be committed"


def test_package_manager_pinned():
    pkg = json.loads((ROOT / "frontend/package.json").read_text())
    assert pkg.get("packageManager") == PIN


def test_dockerfiles_use_pnpm_frozen_lockfile():
    for f in (ROOT / "deploy/Dockerfile.frontend", ROOT / "deploy/Dockerfile.frontend.dev"):
        text = f.read_text()
        assert "corepack prepare pnpm@10.29.3" in text
        assert "pnpm install --frozen-lockfile" in text


def test_ci_uses_pnpm():
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "pnpm/action-setup" in ci
    assert "cache: pnpm" in ci
    assert "pnpm run build" in ci


def test_precommit_hooks_use_pnpm_exec():
    cfg = (ROOT / ".pre-commit-config.yaml").read_text()
    assert "pnpm exec tsc" in cfg
    assert "pnpm exec eslint" in cfg
