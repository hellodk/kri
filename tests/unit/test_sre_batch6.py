"""Unit tests for SRE-level docker-compose configuration (batch 6)."""


def test_docker_compose_has_pg_backup_service():
    from pathlib import Path

    import yaml

    compose = yaml.safe_load((Path(__file__).parent.parent.parent / "deploy/docker-compose.yml").read_text())
    assert "pg_backup" in compose["services"], "pg_backup service must be defined in docker-compose.yml"


def test_pg_backup_has_volume():
    from pathlib import Path

    import yaml

    compose = yaml.safe_load((Path(__file__).parent.parent.parent / "deploy/docker-compose.yml").read_text())
    vols = compose.get("volumes", {})
    assert "pgbackups" in vols, "pgbackups volume must be declared"
