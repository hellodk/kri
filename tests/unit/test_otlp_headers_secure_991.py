"""Issue #991 S1 — otlp_headers must not leak in logs or be stored in cleartext.

`otlp_headers` typically carries an `Authorization: Bearer <token>` value. Two
leaks were found:
  1. `_mask_extravar` didn't match the key, so the token printed verbatim into
     the ansible cmdline header written to `bootstrap_logs` (any viewer can read
     it via GET /nodes/{id}).
  2. `set_setting(OTLP_HEADERS, ...)` was called without `encrypt=True`, unlike
     every other secret-bearing setting — so it sat unencrypted at rest.

Run: pytest tests/unit/test_otlp_headers_secure_991.py -q
"""

from pathlib import Path

from fleet_platform.workers.ansible_tasks import _mask_extravar

_SETTINGS_ROUTE = (
    Path(__file__).resolve().parents[2] / "fleet_platform" / "api" / "routes" / "platform_settings.py"
).read_text()


# ── 1. log masking ───────────────────────────────────────────────────────────


def test_otlp_headers_masked_in_cmdline():
    assert _mask_extravar("otlp_headers", "Authorization=Bearer sk-secret-123") == "****", (
        "otlp_headers carries an auth token and must be redacted in the ansible cmdline log header (#991 S1)."
    )


def test_authorization_and_bearer_keys_masked():
    assert _mask_extravar("authorization", "Bearer xyz") == "****"
    assert _mask_extravar("x_auth_header", "Bearer xyz") == "****"


def test_non_secret_key_still_rendered():
    # Regression guard: the widened heuristic must not redact ordinary values.
    assert _mask_extravar("otlp_endpoint", "http://otel:4318") == "http://otel:4318"


# ── 2. at-rest encryption ────────────────────────────────────────────────────


def test_otlp_headers_persisted_encrypted():
    assert "OTLP_HEADERS, payload.otlp_headers, encrypt=True" in _SETTINGS_ROUTE, (
        "OTLP_HEADERS must be persisted with encrypt=True like every other "
        "secret-bearing setting in this handler (#991 S1)."
    )
