"""
Unit tests for SRE hardening — issues #92, #93, #94, #96.

Covers:
  - Docker image pinning (no :latest tags)
  - Resource limits on all services
  - Health checks on api, worker, beat, frontend
  - celery-redbeat dependency present
  - beat command uses RedBeatScheduler
"""
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent.parent
DOCKER_COMPOSE = REPO_ROOT / "deploy" / "docker-compose.yml"
DOCKERFILE_API = REPO_ROOT / "deploy" / "Dockerfile.api"
DOCKERFILE_FRONTEND = REPO_ROOT / "deploy" / "Dockerfile.frontend"
PYPROJECT = REPO_ROOT / "pyproject.toml"


def _load_compose() -> dict:
    return yaml.safe_load(DOCKER_COMPOSE.read_text())


def test_docker_compose_images_pinned():
    """No service image entry may use :latest."""
    compose = _load_compose()
    services = compose.get("services", {})
    for svc_name, svc_cfg in services.items():
        image = svc_cfg.get("image")
        if image is not None:
            assert ":latest" not in image, (
                f"Service '{svc_name}' uses unpinned image: {image}"
            )


def test_dockerfiles_no_latest_tags():
    """No FROM line in any Dockerfile may reference :latest."""
    for dockerfile in (DOCKERFILE_API, DOCKERFILE_FRONTEND):
        text = dockerfile.read_text()
        for line in text.splitlines():
            if line.strip().upper().startswith("FROM"):
                assert ":latest" not in line, (
                    f"{dockerfile.name}: unpinned FROM line: {line.strip()}"
                )


def test_docker_compose_resource_limits():
    """All 8 services must have deploy.resources.limits.memory set."""
    compose = _load_compose()
    services = compose.get("services", {})
    # salt-master was removed from Docker and now runs natively on mm1 (issue #110)
    expected = ("db", "pg_backup", "redis", "api", "worker", "beat", "frontend")
    for svc_name in expected:
        svc = services[svc_name]
        memory = (
            svc.get("deploy", {})
            .get("resources", {})
            .get("limits", {})
            .get("memory")
        )
        assert memory is not None, (
            f"Service '{svc_name}' missing deploy.resources.limits.memory"
        )


def test_docker_compose_api_healthcheck():
    """api service healthcheck must reference the /health/ready endpoint."""
    compose = _load_compose()
    api = compose["services"]["api"]
    healthcheck = api.get("healthcheck")
    assert healthcheck is not None, "api service has no healthcheck"
    test_cmd = healthcheck.get("test", [])
    assert any("health/ready" in str(part) for part in test_cmd), (
        f"api healthcheck does not reference health/ready: {test_cmd}"
    )


def test_docker_compose_beat_healthcheck():
    """beat service must have a healthcheck configured."""
    compose = _load_compose()
    beat = compose["services"]["beat"]
    assert beat.get("healthcheck") is not None, "beat service has no healthcheck"


def test_docker_compose_worker_healthcheck():
    """worker service must have a healthcheck configured."""
    compose = _load_compose()
    assert compose["services"]["worker"].get("healthcheck") is not None, "worker service has no healthcheck"


def test_docker_compose_frontend_healthcheck():
    """frontend service must have a healthcheck configured."""
    compose = _load_compose()
    assert compose["services"]["frontend"].get("healthcheck") is not None, "frontend service has no healthcheck"


def test_pyproject_has_celery_redbeat():
    """celery-redbeat must be listed in pyproject.toml dependencies."""
    text = PYPROJECT.read_text()
    assert "celery-redbeat" in text, (
        "celery-redbeat not found in pyproject.toml dependencies"
    )


def test_celery_beat_command_uses_redbeat_scheduler():
    """beat service command must include the RedBeatScheduler flag."""
    compose = _load_compose()
    beat = compose["services"]["beat"]
    command = beat.get("command", [])
    assert any("redbeat.RedBeatScheduler" in str(part) for part in command), (
        f"beat service command does not use redbeat.RedBeatScheduler: {command}"
    )
