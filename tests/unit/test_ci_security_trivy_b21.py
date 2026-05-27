"""
Tests for CI security fixes — issues #97, #108, #100.

#97 / #108: Trivy and build tools removed from production API container (multi-stage Dockerfile)
#100: pip-audit + Trivy container-scan jobs added to CI pipeline
"""

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent


def test_dockerfile_api_no_curl_pipe_sh() -> None:
    """Dockerfile.api must not use curl|sh (supply chain attack vector)."""
    src = (REPO_ROOT / "deploy" / "Dockerfile.api").read_text()
    assert "curl -sfL" not in src, "curl -sfL found in Dockerfile.api — remove supply-chain install"
    assert "| sh" not in src, "pipe-to-sh found in Dockerfile.api — remove supply-chain install"


def test_dockerfile_api_no_trivy_in_runtime() -> None:
    """Trivy must not be installed in any stage of Dockerfile.api."""
    src = (REPO_ROOT / "deploy" / "Dockerfile.api").read_text()
    assert "trivy" not in src.lower(), (
        "trivy found in Dockerfile.api — it must be run in CI, not baked into the production image"
    )


def test_dockerfile_api_is_multistage() -> None:
    """Dockerfile.api must use a multi-stage build (at least 2 FROM directives)."""
    src = (REPO_ROOT / "deploy" / "Dockerfile.api").read_text()
    assert src.count("FROM ") >= 2, (
        f"Expected at least 2 FROM stages in Dockerfile.api, found {src.count('FROM ')}"
    )


def test_ci_has_dependency_audit() -> None:
    """CI workflow must include a pip-audit dependency audit job."""
    src = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "pip-audit" in src, "pip-audit not found in ci.yml — add dependency-audit job"


def test_ci_has_container_scan() -> None:
    """CI workflow must include a Trivy container-scan job."""
    src = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "trivy-action" in src, "trivy-action not found in ci.yml — add container-scan job"


def test_dockerfile_api_runtime_has_venv_copy() -> None:
    """Runtime stage must copy .venv from builder (otherwise app has no packages)."""
    src = (REPO_ROOT / "deploy" / "Dockerfile.api").read_text()
    assert "COPY --from=builder /app/.venv /app/.venv" in src, (
        "Dockerfile.api runtime stage must copy .venv from builder"
    )


def test_dockerfile_api_runtime_has_venv_path() -> None:
    """Runtime stage must set PATH to include .venv/bin (otherwise python/uvicorn not found)."""
    src = (REPO_ROOT / "deploy" / "Dockerfile.api").read_text()
    assert 'PATH="/app/.venv/bin:$PATH"' in src, (
        "Dockerfile.api runtime stage must set PATH to /app/.venv/bin"
    )
