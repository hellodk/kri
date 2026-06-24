"""Property-based tests for pure helper functions (#808).

Covers:
- fleet_platform.core.validators.validate_minion_id
- fleet_platform.core.redaction.redact_cmdline

Invariants asserted:
- valid IDs are accepted (no false negatives for the allowed charset)
- invalid IDs always raise ValueError (no false positives)
- idempotence: redact(redact(x)) == redact(x)
- redacted output never contains the secret value
- redact never raises for any string input
- redact(None) returns None
"""

from __future__ import annotations

import string

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fleet_platform.core.redaction import redact_cmdline
from fleet_platform.core.validators import MINION_ID_RE, validate_minion_id

# ---------------------------------------------------------------------------
# validate_minion_id — invariants
# ---------------------------------------------------------------------------

VALID_CHARSET = string.ascii_letters + string.digits + "._-"

VALID_MINION_ID = st.text(
    alphabet=VALID_CHARSET,
    min_size=1,
    max_size=128,
)

INVALID_MINION_ID = st.one_of(
    # Empty string
    st.just(""),
    # Too long (> 128 chars)
    st.text(alphabet=VALID_CHARSET, min_size=129, max_size=200),
    # Contains forbidden character(s)
    st.text(
        alphabet=st.characters(
            blacklist_categories=("Lu", "Ll", "Nd"),
            blacklist_characters="._-",
            whitelist_characters="!@#$%^&*()+=[]{}|;:,<>?/\\ \"'`~",
        ),
        min_size=1,
        max_size=50,
    ).filter(lambda s: not MINION_ID_RE.match(s)),
)


@given(VALID_MINION_ID)
def test_validate_minion_id_accepts_valid(minion_id: str) -> None:
    """validate_minion_id must return the value unchanged for any valid ID."""
    result = validate_minion_id(minion_id)
    assert result == minion_id


@given(INVALID_MINION_ID)
def test_validate_minion_id_rejects_invalid(minion_id: str) -> None:
    """validate_minion_id must raise ValueError for any invalid ID."""
    with pytest.raises(ValueError):
        validate_minion_id(minion_id)


@given(VALID_MINION_ID)
def test_validate_minion_id_is_idempotent(minion_id: str) -> None:
    """Applying validate_minion_id twice on a valid ID gives the same result."""
    once = validate_minion_id(minion_id)
    twice = validate_minion_id(once)
    assert once == twice


@given(VALID_MINION_ID)
def test_validate_minion_id_output_length_bound(minion_id: str) -> None:
    """The returned value is always 1-128 characters long."""
    result = validate_minion_id(minion_id)
    assert 1 <= len(result) <= 128


# ---------------------------------------------------------------------------
# redact_cmdline — invariants
# ---------------------------------------------------------------------------

PRINTABLE_TEXT = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd", "Zs", "Po", "Pd", "Ps", "Pe"),
        whitelist_characters="=:/._-@",
    ),
    max_size=300,
)


@given(st.text(max_size=500))
@settings(max_examples=200, deadline=3000)
def test_redact_cmdline_never_raises(text: str) -> None:
    """redact_cmdline must not raise for any string input."""
    result = redact_cmdline(text)
    assert result is None or isinstance(result, str)


def test_redact_cmdline_none_returns_none() -> None:
    result = redact_cmdline(None)
    assert result is None


def test_redact_cmdline_empty_returns_empty() -> None:
    result = redact_cmdline("")
    assert result == ""


@given(PRINTABLE_TEXT)
@settings(max_examples=150, deadline=3000)
def test_redact_cmdline_idempotent(text: str) -> None:
    """redact(redact(x)) == redact(x) for any input."""
    once = redact_cmdline(text)
    twice = redact_cmdline(once)
    assert once == twice


@pytest.mark.parametrize(
    "cmdline,secret",
    [
        # CLI flag-style: --flag=value or --flag value
        ("app --password=s3cr3t --host=db", "s3cr3t"),
        ("app --token hunter2 --debug", "hunter2"),
        ("app --secret-key=abc123xyz", "abc123xyz"),
        ("app --client-secret xyzzy99", "xyzzy99"),
        ("app --passwd top_secret", "top_secret"),
        # Environment variable style: KEY=value
        ("export API_KEY=supersecret123", "supersecret123"),
        # URL credential style: scheme://user:pass@host
        ("psql postgres://user:p4ssw0rd@host/db", "p4ssw0rd"),
    ],
)
def test_redact_cmdline_removes_secret_value(cmdline: str, secret: str) -> None:
    """Known sensitive flags/env vars must have their values replaced."""
    result = redact_cmdline(cmdline)
    assert result is not None
    assert secret not in result, f"Secret {secret!r} survived redaction in: {result!r}"
    assert "<REDACTED>" in result


@pytest.mark.parametrize(
    "cmdline",
    [
        "app --host myhost --port 5432",
        "python manage.py migrate",
        "ls -la /tmp",
        "echo hello world",
    ],
)
def test_redact_cmdline_preserves_innocuous_input(cmdline: str) -> None:
    """Strings without sensitive flags must be returned unchanged."""
    assert redact_cmdline(cmdline) == cmdline
