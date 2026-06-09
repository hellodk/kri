"""Behavioral tests for fleet_platform.core.redaction.redact_cmdline.

Source-contract test: verifies ingest.py calls redact_cmdline so the gate
cannot be silently removed.
"""

from pathlib import Path

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
# Source-contract: ingest.py must call redact_cmdline in ingest_process_stats
# ---------------------------------------------------------------------------


def test_ingest_calls_redact_cmdline():
    """Verify ingest.py references redact_cmdline so the guard cannot be silently removed."""
    ingest_path = Path(__file__).resolve().parents[2] / "fleet_platform" / "api" / "routes" / "ingest.py"
    source = ingest_path.read_text()
    assert "redact_cmdline(" in source, (
        "ingest.py must call redact_cmdline() in ingest_process_stats — secret guard was silently removed"
    )
