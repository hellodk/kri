"""SRE batch 7 security tests — docker-compose insecure defaults (issue #98)."""


def test_docker_compose_no_insecure_postgres_default():
    from pathlib import Path

    import yaml
    compose = yaml.safe_load((Path(__file__).parent.parent.parent / "deploy/docker-compose.yml").read_text())
    # The POSTGRES_PASSWORD value must not contain ':-fleet' (insecure default)
    pg_pass = compose["services"]["db"]["environment"].get("POSTGRES_PASSWORD", "")
    assert ":-fleet" not in str(pg_pass), "POSTGRES_PASSWORD must not have insecure :-fleet default"
    assert ":?" in str(pg_pass), "POSTGRES_PASSWORD should use :? to require the variable"


def test_docker_compose_no_insecure_redis_default():
    from pathlib import Path
    content = (Path(__file__).parent.parent.parent / "deploy/docker-compose.yml").read_text()
    assert ":-redispass" not in content, "docker-compose must not contain insecure :-redispass default"
