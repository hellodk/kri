"""
Deploy parity tests — issue #577.

Asserts that:
1. k8s manifests have Deployment + Service for api/worker/beat/frontend with liveness + readiness probes.
2. docker-compose.yml has no hardcoded /home/dk absolute paths.
3. ci.yml has no :latest image tags.
"""

import re
from pathlib import Path

import pytest
import yaml

DEPLOY = Path(__file__).parents[2] / "deploy"
K8S = DEPLOY / "k8s"
COMPOSE = DEPLOY / "docker-compose.yml"
CI = Path(__file__).parents[2] / ".github" / "workflows" / "ci.yml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> dict:
    with open(path) as fh:
        return yaml.safe_load(fh)


def _k8s_deployments() -> dict[str, dict]:
    """Return {name: manifest} for every Deployment in deploy/k8s/."""
    deployments: dict[str, dict] = {}
    for p in K8S.glob("*.yaml"):
        try:
            doc = _load_yaml(p)
        except Exception:
            continue
        if isinstance(doc, dict) and doc.get("kind") == "Deployment":
            name = doc["metadata"]["name"]
            deployments[name] = doc
    return deployments


def _k8s_services() -> dict[str, dict]:
    """Return {name: manifest} for every Service in deploy/k8s/."""
    services: dict[str, dict] = {}
    for p in K8S.glob("*.yaml"):
        try:
            doc = _load_yaml(p)
        except Exception:
            continue
        if isinstance(doc, dict) and doc.get("kind") == "Service":
            name = doc["metadata"]["name"]
            services[name] = doc
    return services


def _container_spec(deployment: dict) -> dict:
    """Return the first container spec from a Deployment manifest."""
    return deployment["spec"]["template"]["spec"]["containers"][0]


# ---------------------------------------------------------------------------
# k8s Deployment existence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "deployment_name",
    [
        "kri-api",
        "kri-worker",
        "kri-beat",
        "kri-frontend",
    ],
)
def test_k8s_deployment_exists(deployment_name: str) -> None:
    deployments = _k8s_deployments()
    assert deployment_name in deployments, (
        f"Missing k8s Deployment '{deployment_name}' in deploy/k8s/ — "
        "add {deployment_name.replace('kri-', '')}-deployment.yaml"
    )


# ---------------------------------------------------------------------------
# k8s Service existence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "service_name",
    [
        "kri-api",
        "kri-frontend",
    ],
)
def test_k8s_service_exists(service_name: str) -> None:
    services = _k8s_services()
    assert service_name in services, (
        f"Missing k8s Service '{service_name}' in deploy/k8s/ — add {{service_name.replace('kri-', '')}}-service.yaml"
    )


# ---------------------------------------------------------------------------
# Liveness + readiness probes on each Deployment
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "deployment_name",
    [
        "kri-api",
        "kri-worker",
        "kri-beat",
        "kri-frontend",
    ],
)
def test_k8s_deployment_has_liveness_probe(deployment_name: str) -> None:
    deployments = _k8s_deployments()
    assert deployment_name in deployments, f"Deployment {deployment_name!r} missing"
    container = _container_spec(deployments[deployment_name])
    assert "livenessProbe" in container, f"Deployment '{deployment_name}' container has no livenessProbe"


@pytest.mark.parametrize(
    "deployment_name",
    [
        "kri-api",
        "kri-worker",
        "kri-beat",
        "kri-frontend",
    ],
)
def test_k8s_deployment_has_readiness_probe(deployment_name: str) -> None:
    deployments = _k8s_deployments()
    assert deployment_name in deployments, f"Deployment {deployment_name!r} missing"
    container = _container_spec(deployments[deployment_name])
    assert "readinessProbe" in container, f"Deployment '{deployment_name}' container has no readinessProbe"


# ---------------------------------------------------------------------------
# Ingress targets match the Services we ship
# ---------------------------------------------------------------------------


def test_ingress_targets_have_matching_services() -> None:
    """The ingress.yaml targets kri-api:8000 and kri-frontend:80 — both Services must exist."""
    ingress_path = K8S / "ingress.yaml"
    assert ingress_path.exists(), "deploy/k8s/ingress.yaml is missing"
    ingress = _load_yaml(ingress_path)
    services = _k8s_services()

    backend_names: set[str] = set()
    for rule in ingress.get("spec", {}).get("rules", []):
        for path in rule.get("http", {}).get("paths", []):
            svc_name = path["backend"]["service"]["name"]
            backend_names.add(svc_name)

    for svc_name in backend_names:
        assert svc_name in services, f"Ingress references Service '{svc_name}' but no matching Service manifest found"


# ---------------------------------------------------------------------------
# docker-compose.yml — no hardcoded /home/dk absolute paths
# ---------------------------------------------------------------------------


def test_compose_has_no_hardcoded_home_dk_paths() -> None:
    content = COMPOSE.read_text()
    # Find every /home/dk/... occurrence in the file
    all_occurrences = re.findall(r"/home/dk/[^\s:\"']+", content)
    # Keep only those that are NOT part of a ${VAR:-/home/dk/...} default expression
    hardcoded = [occ for occ in all_occurrences if not re.search(r"\$\{[^}]*:-" + re.escape(occ), content)]
    assert not hardcoded, (
        f"docker-compose.yml still has hardcoded /home/dk paths: {hardcoded}. "
        "Replace with ${{VAR:-default}} env-driven paths."
    )


def test_compose_env_var_pattern_for_pulse_repos() -> None:
    content = COMPOSE.read_text()
    assert "PULSE_REPOS_DIR" in content, (
        "docker-compose.yml should use ${PULSE_REPOS_DIR:-...} for the pulse repos bind-mount"
    )


def test_compose_env_var_pattern_for_playbooks_files() -> None:
    content = COMPOSE.read_text()
    assert "PLAYBOOKS_FILES_DIR" in content, (
        "docker-compose.yml should use ${PLAYBOOKS_FILES_DIR:-...} for the playbooks/files bind-mount"
    )


# ---------------------------------------------------------------------------
# ci.yml — no :latest image tags
# ---------------------------------------------------------------------------


def test_ci_yml_has_no_latest_image_tags() -> None:
    content = CI.read_text()
    # Find image: ... lines and check for :latest
    latest_hits = re.findall(r"image:\s+\S+:latest\S*", content)
    assert not latest_hits, (
        f"ci.yml still references :latest image tags: {latest_hits}. "
        "Pin to an exact version (e.g. timescale/timescaledb:2.26.4-pg17)."
    )


def test_ci_yml_timescaledb_pinned_to_exact_version() -> None:
    content = CI.read_text()
    assert "timescale/timescaledb:2.26.4-pg17" in content, (
        "ci.yml timescaledb service image should be pinned to 2.26.4-pg17 (matching deploy/docker-compose.yml)"
    )
