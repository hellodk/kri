"""Behavioral tests for fleet_platform.core.redaction.redact_cmdline.

Also drives the ingest_process_stats route end-to-end (DB mocked) to prove the
secret-redaction gate is actually applied to rows written to the database — not
merely that the source references redact_cmdline (#800).
"""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from fleet_platform.core.redaction import redact_cmdline

# ---------------------------------------------------------------------------
# --flag=value style
# ---------------------------------------------------------------------------


def test_password_flag_redacted():
    result = redact_cmdline("python serve.py --password=hunter2 --port 8080")
    assert "--password=<REDACTED>" in result
    assert "--port 8080" in result


def test_token_flag_redacted():
    result = redact_cmdline("myapp --token=abc123 --verbose")
    assert "--token=<REDACTED>" in result
    assert "--verbose" in result


def test_api_key_hyphen_redacted():
    result = redact_cmdline("cli --api-key=sk-live-xyz789 --output json")
    assert "--api-key=<REDACTED>" in result
    assert "--output json" in result


def test_api_key_underscore_redacted():
    result = redact_cmdline("cli --api_key=sk-live-xyz789 --output json")
    assert "--api_key=<REDACTED>" in result
    assert "--output json" in result


def test_secret_flag_redacted():
    result = redact_cmdline("app --secret=topsecret --mode prod")
    assert "--secret=<REDACTED>" in result
    assert "--mode prod" in result


def test_client_secret_flag_redacted():
    result = redact_cmdline("oauth --client-secret=csec_abc --client-id=public")
    assert "--client-secret=<REDACTED>" in result
    assert "--client-id=public" in result


# ---------------------------------------------------------------------------
# env-var style  KEY=VALUE
# ---------------------------------------------------------------------------


def test_env_aws_secret_access_key_redacted():
    result = redact_cmdline("AWS_SECRET_ACCESS_KEY=AKIAxxx GITHUB_TOKEN=ghp_x python app")
    assert "AWS_SECRET_ACCESS_KEY=<REDACTED>" in result
    assert "GITHUB_TOKEN=<REDACTED>" in result
    assert "python app" in result


def test_env_non_secret_not_redacted():
    result = redact_cmdline("FOO=bar python app.py")
    assert "FOO=bar" in result


def test_env_password_redacted():
    result = redact_cmdline("DB_PASSWORD=s3cret DB_HOST=localhost myapp")
    assert "DB_PASSWORD=<REDACTED>" in result
    assert "DB_HOST=localhost" in result


# ---------------------------------------------------------------------------
# URL credentials  scheme://user:pass@host
# ---------------------------------------------------------------------------


def test_url_credentials_redacted():
    result = redact_cmdline("psql postgres://user:s3cret@db:5432/x")
    assert "user:<REDACTED>@" in result
    # host and db-name survive
    assert "db:5432/x" in result


def test_url_credentials_mysql_redacted():
    result = redact_cmdline("mysqldump mysql://admin:password123@127.0.0.1:3306/mydb")
    assert "admin:<REDACTED>@" in result
    assert "127.0.0.1:3306/mydb" in result


# ---------------------------------------------------------------------------
# None / empty passthrough
# ---------------------------------------------------------------------------


def test_none_returns_none():
    assert redact_cmdline(None) is None


def test_empty_string_returns_empty():
    assert redact_cmdline("") == ""


def test_no_secrets_unchanged():
    cmd = "python -m http.server 8000"
    assert redact_cmdline(cmd) == cmd


# ---------------------------------------------------------------------------
# Behavioral wiring: ingest_process_stats must redact cmdline before the DB write
# ---------------------------------------------------------------------------


def _unwrap(func):
    """Return the undecorated coroutine behind slowapi's @limiter.limit wrapper."""
    return getattr(func, "__wrapped__", func)


@pytest.mark.asyncio
async def test_ingest_process_stats_redacts_cmdline_before_db_write():
    """Drive ingest_process_stats and assert the row sent to the DB carries the
    redacted command line — the secret value must never reach the INSERT."""
    import uuid

    from fleet_platform.api.routes import ingest
    from fleet_platform.schemas.ingest import ProcessStatItem, ProcessStatsIngestPayload

    secret = "hunter2supersecret"
    payload = ProcessStatsIngestPayload(
        minion_id="mac-01",
        processes=[ProcessStatItem(pid=42, name="serve", cmdline=f"python serve.py --password={secret} --port 8080")],
    )

    fake_node = type("Node", (), {"id": uuid.uuid4()})()
    db = AsyncMock()

    with patch.object(ingest, "_resolve_node", AsyncMock(return_value=fake_node)):
        result = await _unwrap(ingest.ingest_process_stats)(
            request=object(),
            payload=payload,
            x_node_token="tok-123",
            db=db,
        )

    assert result["rows"] == 1
    # Capture the INSERT statement actually handed to the DB and inspect its bound params.
    assert db.execute.await_count == 1
    stmt = db.execute.await_args.args[0]
    params = stmt.compile(dialect=postgresql.dialect()).params
    param_values = [str(v) for v in params.values()]

    # The raw secret must NOT appear in any bound parameter; the redacted form must.
    assert not any(secret in v for v in param_values), f"raw secret leaked into INSERT params: {param_values}"
    assert any("--password=<REDACTED>" in v for v in param_values), (
        f"redacted cmdline not found in INSERT params: {param_values}"
    )


@pytest.mark.asyncio
async def test_ingest_process_stats_rejects_missing_token():
    """No token → 401, and nothing is written (auth gate precedes redaction)."""
    from fastapi import HTTPException

    from fleet_platform.api.routes import ingest
    from fleet_platform.schemas.ingest import ProcessStatItem, ProcessStatsIngestPayload

    payload = ProcessStatsIngestPayload(
        minion_id="mac-01",
        processes=[ProcessStatItem(pid=1, name="x", cmdline="echo hi")],
    )
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await _unwrap(ingest.ingest_process_stats)(request=object(), payload=payload, x_node_token=None, db=db)
    assert exc.value.status_code == 401
    db.execute.assert_not_called()
