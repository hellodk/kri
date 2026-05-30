# tests/unit/test_salt_allowlist.py
"""Unit tests for the dynamic Salt function allowlist (issue #255)."""

import json
import time
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(setting_value: str | None):
    """Return a minimal mock synchronous SQLAlchemy Session whose
    execute().scalar_one_or_none() returns a PlatformSetting-like object."""
    row = None
    if setting_value is not None:
        row = MagicMock()
        row.value = setting_value
        row.is_encrypted = False

    scalar_mock = MagicMock()
    scalar_mock.scalar_one_or_none.return_value = row

    db = MagicMock()
    db.execute.return_value = scalar_mock
    return db


def _reset_cache():
    """Force the module-level cache back to None between tests."""
    import fleet_platform.services.platform_settings_svc as svc

    svc._allowed_cache = None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_get_allowed_returns_defaults_when_no_db_setting():
    """When no DB row exists the helper must return the compiled default set."""
    _reset_cache()
    from fleet_platform.services.platform_settings_svc import (
        _DEFAULT_SALT_FUNCTIONS,
        _SALT_MINIMUM_FUNCTIONS,
        get_allowed_salt_functions_sync,
    )

    db = _make_db(None)  # no DB row
    result = get_allowed_salt_functions_sync(db)

    expected = _DEFAULT_SALT_FUNCTIONS | _SALT_MINIMUM_FUNCTIONS
    assert result == expected, f"Expected defaults, got {sorted(result)}"
    # Must be a frozenset
    assert isinstance(result, frozenset)


def test_get_allowed_reads_db_setting_when_present():
    """When a valid JSON array is stored the helper returns those functions."""
    _reset_cache()
    from fleet_platform.services.platform_settings_svc import (
        _SALT_MINIMUM_FUNCTIONS,
        get_allowed_salt_functions_sync,
    )

    stored = json.dumps(["state.apply", "test.ping", "pkg.install"])
    db = _make_db(stored)
    result = get_allowed_salt_functions_sync(db)

    assert "state.apply" in result
    assert "pkg.install" in result
    # Minimum functions are always merged in
    for fn in _SALT_MINIMUM_FUNCTIONS:
        assert fn in result, f"Minimum function {fn!r} missing from result"


def test_get_allowed_merges_minimum_functions_even_if_removed():
    """Minimum functions (test.ping, grains.items, grains.get) must always be
    present even when the stored list deliberately omits them."""
    _reset_cache()
    from fleet_platform.services.platform_settings_svc import (
        _SALT_MINIMUM_FUNCTIONS,
        get_allowed_salt_functions_sync,
    )

    # Store a list that intentionally excludes all minimum functions
    stored = json.dumps(["state.apply", "disk.usage"])
    db = _make_db(stored)
    result = get_allowed_salt_functions_sync(db)

    for fn in _SALT_MINIMUM_FUNCTIONS:
        assert fn in result, (
            f"Minimum function {fn!r} should always be present but is missing. "
            f"Got: {sorted(result)}"
        )


def test_get_allowed_falls_back_on_invalid_json():
    """Corrupted DB value must not crash — it silently falls back to defaults."""
    _reset_cache()
    from fleet_platform.services.platform_settings_svc import (
        _DEFAULT_SALT_FUNCTIONS,
        _SALT_MINIMUM_FUNCTIONS,
        get_allowed_salt_functions_sync,
    )

    db = _make_db("not-valid-json{{")
    result = get_allowed_salt_functions_sync(db)

    expected = _DEFAULT_SALT_FUNCTIONS | _SALT_MINIMUM_FUNCTIONS
    assert result == expected


def test_cache_returns_cached_value_within_60s():
    """A second call within 60 s must return the same frozenset without hitting DB."""
    _reset_cache()
    import fleet_platform.services.platform_settings_svc as svc
    from fleet_platform.services.platform_settings_svc import get_allowed_salt_functions_sync

    stored = json.dumps(["state.apply", "test.ping"])
    db = _make_db(stored)

    first = get_allowed_salt_functions_sync(db)
    # Reset the db mock call count so we can detect re-reads
    db.execute.reset_mock()

    second = get_allowed_salt_functions_sync(db)

    # Should be the same object (cache hit)
    assert first == second
    # DB must NOT have been queried again
    db.execute.assert_not_called()


def test_cache_expires_after_60s():
    """After 60 seconds the cache must be invalidated and the DB re-queried."""
    _reset_cache()
    import fleet_platform.services.platform_settings_svc as svc
    from fleet_platform.services.platform_settings_svc import get_allowed_salt_functions_sync

    stored = json.dumps(["state.apply", "test.ping"])
    db = _make_db(stored)

    # Prime the cache
    get_allowed_salt_functions_sync(db)
    db.execute.reset_mock()

    # Simulate passage of 61 seconds by backdating the cache timestamp
    assert svc._allowed_cache is not None
    svc._allowed_cache = (svc._allowed_cache[0] - 61, svc._allowed_cache[1])

    get_allowed_salt_functions_sync(db)
    # DB must have been re-queried after expiry
    db.execute.assert_called_once()


def test_invalidate_salt_allowlist_cache_clears_cache():
    """invalidate_salt_allowlist_cache() must set _allowed_cache to None."""
    import fleet_platform.services.platform_settings_svc as svc
    from fleet_platform.services.platform_settings_svc import (
        get_allowed_salt_functions_sync,
        invalidate_salt_allowlist_cache,
    )

    _reset_cache()
    db = _make_db(json.dumps(["test.ping"]))
    get_allowed_salt_functions_sync(db)  # prime
    assert svc._allowed_cache is not None

    invalidate_salt_allowlist_cache()
    assert svc._allowed_cache is None


def test_default_salt_functions_constant_is_correct():
    """Smoke-test that the default set contains the original hardcoded functions."""
    from fleet_platform.services.platform_settings_svc import _DEFAULT_SALT_FUNCTIONS

    expected_subset = {
        "state.apply",
        "state.highstate",
        "test.ping",
        "grains.items",
        "pkg.install",
        "service.restart",
        "cmd.run",
        "disk.usage",
        "saltutil.sync_all",
    }
    for fn in expected_subset:
        assert fn in _DEFAULT_SALT_FUNCTIONS, f"{fn!r} missing from _DEFAULT_SALT_FUNCTIONS"
