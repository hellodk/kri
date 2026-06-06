"""#428: frontend Docker build fixes — pinned node base + .dockerignore."""

from pathlib import Path

ROOT = Path(__file__).parent.parent.parent


def test_both_frontend_dockerfiles_pinned_to_fixed_node():
    for f in ("deploy/Dockerfile.frontend", "deploy/Dockerfile.frontend.dev"):
        text = (ROOT / f).read_text()
        assert "node:22.22.3-alpine3.22" in text, f"{f} not pinned to fixed node base"
        # no unpinned node tag
        assert "FROM node:22-alpine\n" not in text and "node:22.12.0" not in text


def test_dockerignore_excludes_node_modules():
    di = (ROOT / ".dockerignore").read_text()
    assert "node_modules" in di, "node_modules must be excluded (pnpm symlink clash on COPY)"
    assert ".venv" in di and ".git" in di
