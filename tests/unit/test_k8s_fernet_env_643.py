"""Test for GitHub issue #643: fix FERNET_KEY env var naming and set ENVIRONMENT."""

import re
from pathlib import Path

import yaml


def test_fernet_secret_key_renamed_in_deployments():
    """Verify FERNET_KEY is renamed to FERNET_SECRET_KEY in all deployment manifests."""
    deploy_dir = Path(__file__).resolve().parents[2] / "deploy" / "k8s"

    deployment_files = [
        "api-deployment.yaml",
        "worker-deployment.yaml",
        "beat-deployment.yaml",
        "worker-ansible-deployment.yaml",
    ]

    for filename in deployment_files:
        filepath = deploy_dir / filename
        assert filepath.exists(), f"Expected manifest {filepath} not found"

        with open(filepath) as f:
            content = f.read()

        # FERNET_KEY should NOT appear anywhere
        assert "FERNET_KEY" not in content, (
            f"{filename}: FERNET_KEY still present — should be renamed to FERNET_SECRET_KEY"
        )

        # FERNET_SECRET_KEY must appear (both in env name and secretKeyRef key)
        assert "FERNET_SECRET_KEY" in content, f"{filename}: FERNET_SECRET_KEY not found — rename was not completed"

        # Parse as YAML to ensure structure is valid
        docs = list(yaml.safe_load_all(content))
        assert len(docs) > 0, f"{filename}: YAML parsing failed"


def test_fernet_secret_key_in_secret_template():
    """Verify FERNET_KEY is renamed to FERNET_SECRET_KEY in secret.yaml.template."""
    deploy_dir = Path(__file__).resolve().parents[2] / "deploy" / "k8s"
    filepath = deploy_dir / "secret.yaml.template"

    assert filepath.exists(), f"Expected manifest {filepath} not found"

    with open(filepath) as f:
        content = f.read()

    # FERNET_KEY should NOT appear in comments or data section
    assert "FERNET_KEY" not in content, (
        "secret.yaml.template: FERNET_KEY still present — should be renamed to FERNET_SECRET_KEY"
    )

    # FERNET_SECRET_KEY must appear in both comment and data key
    assert "FERNET_SECRET_KEY" in content, (
        "secret.yaml.template: FERNET_SECRET_KEY not found — rename was not completed"
    )


def test_environment_set_in_configmap():
    """#1050: the invalid-by-construction configmap.yaml ($(VAR) shell expansion in
    ConfigMap data) was removed. ENVIRONMENT=production must come from the env files
    that compose actually reads; k8s deployments inline their env."""
    deploy_dir = Path(__file__).resolve().parents[2] / "deploy" / "k8s"
    assert not (deploy_dir / "configmap.yaml").exists(), (
        "configmap.yaml embedded $(POSTGRES_PASSWORD) which only works in pod env — "
        "it must stay deleted unless rewritten without shell expansion"
    )

    for env_example in (
        Path(__file__).resolve().parents[2] / ".env.docker.example",
        Path(__file__).resolve().parents[2] / "deploy" / ".env.docker.example",
    ):
        content = env_example.read_text()
        assert re.search(r"^ENVIRONMENT=production\s*$", content, re.M), (
            f"{env_example.name}: ENVIRONMENT=production missing"
        )
