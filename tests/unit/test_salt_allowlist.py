# tests/unit/test_salt_allowlist.py
"""Unit tests for the dynamic Salt function allowlist (issue #255)."""

import json
from unittest.mock import MagicMock

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


# ---------------------------------------------------------------------------
# Deny list tests
# ---------------------------------------------------------------------------


def _reset_deny_cache():
    """Force the deny-list module-level cache back to None between tests."""
    import fleet_platform.services.platform_settings_svc as svc

    svc._deny_cache = None


def _make_dual_db(allowlist_value: str | None, denylist_value: str | None):
    """Return a mock Session that returns different rows for allowlist vs denylist keys.

    Matches on the WHERE clause embedded in the SQLAlchemy statement by inspecting
    the call arguments; falls back to a simple alternating approach using call count.
    """
    import fleet_platform.services.platform_settings_svc as svc

    call_count = [0]

    def side_effect(stmt):
        key_being_fetched = None
        # Inspect the WHERE clause comparisons to determine which key is requested
        try:
            where = stmt.whereclause
            key_being_fetched = where.right.value  # type: ignore[attr-defined]
        except Exception:
            pass

        row_value = None
        if key_being_fetched == svc.SALT_DENIED_FUNCTIONS:
            row_value = denylist_value
        elif key_being_fetched == svc.SALT_ALLOWED_FUNCTIONS:
            row_value = allowlist_value
        else:
            # Fallback: alternate between allowlist and denylist by call order
            call_count[0] += 1
            row_value = allowlist_value if call_count[0] % 2 == 1 else denylist_value

        row = None
        if row_value is not None:
            row = MagicMock()
            row.value = row_value
            row.is_encrypted = False

        scalar_mock = MagicMock()
        scalar_mock.scalar_one_or_none.return_value = row
        return scalar_mock

    db = MagicMock()
    db.execute.side_effect = side_effect
    return db


def test_denied_functions_are_blocked():
    """A function on the deny list cannot be called even if it is on the allow list."""
    _reset_cache()
    _reset_deny_cache()
    import json

    from fleet_platform.services.platform_settings_svc import get_allowed_salt_functions_sync

    allowlist = json.dumps(["state.apply", "cmd.run", "disk.usage", "test.ping"])
    denylist = json.dumps(["cmd.run"])
    db = _make_dual_db(allowlist, denylist)

    result = get_allowed_salt_functions_sync(db)

    assert "cmd.run" not in result, "'cmd.run' is on the deny list and must be blocked"
    assert "state.apply" in result, "'state.apply' should still be allowed"
    assert "disk.usage" in result, "'disk.usage' should still be allowed"


def test_minimum_functions_cannot_be_denied():
    """test.ping, grains.items, grains.get are always allowed even if on the deny list."""
    _reset_cache()
    _reset_deny_cache()
    import json

    from fleet_platform.services.platform_settings_svc import (
        _SALT_MINIMUM_FUNCTIONS,
        get_allowed_salt_functions_sync,
    )

    # Put all minimum functions on the deny list
    denylist = json.dumps(sorted(_SALT_MINIMUM_FUNCTIONS))
    db = _make_dual_db(None, denylist)

    result = get_allowed_salt_functions_sync(db)

    for fn in _SALT_MINIMUM_FUNCTIONS:
        assert fn in result, (
            f"Minimum function {fn!r} must never be blocked by the deny list, "
            f"but it was absent from the result: {sorted(result)}"
        )


def test_deny_cache_hit_within_60s():
    """A second call to get_denied_salt_functions_sync within 60s must use the cache."""
    _reset_deny_cache()
    import json

    from fleet_platform.services.platform_settings_svc import get_denied_salt_functions_sync

    denylist = json.dumps(["cmd.run", "system.reboot"])
    db = _make_db(denylist)

    first = get_denied_salt_functions_sync(db)
    db.execute.reset_mock()

    second = get_denied_salt_functions_sync(db)

    assert first == second
    db.execute.assert_not_called()


def test_deny_cache_expires_after_60s():
    """After 60 seconds the deny cache must expire and the DB must be re-queried."""
    _reset_deny_cache()
    import json

    import fleet_platform.services.platform_settings_svc as svc
    from fleet_platform.services.platform_settings_svc import get_denied_salt_functions_sync

    denylist = json.dumps(["cmd.run"])
    db = _make_db(denylist)

    get_denied_salt_functions_sync(db)
    db.execute.reset_mock()

    assert svc._deny_cache is not None
    svc._deny_cache = (svc._deny_cache[0] - 61, svc._deny_cache[1])

    get_denied_salt_functions_sync(db)
    db.execute.assert_called_once()


def test_invalidate_salt_deny_cache_clears_cache():
    """invalidate_salt_deny_cache() must set _deny_cache to None."""
    import json

    import fleet_platform.services.platform_settings_svc as svc
    from fleet_platform.services.platform_settings_svc import (
        get_denied_salt_functions_sync,
        invalidate_salt_deny_cache,
    )

    _reset_deny_cache()
    db = _make_db(json.dumps(["cmd.run"]))
    get_denied_salt_functions_sync(db)
    assert svc._deny_cache is not None

    invalidate_salt_deny_cache()
    assert svc._deny_cache is None


def test_empty_denylist_allows_all_allowlisted_functions():
    """When the deny list is empty every allowlisted function is available."""
    _reset_cache()
    _reset_deny_cache()
    import json

    from fleet_platform.services.platform_settings_svc import get_allowed_salt_functions_sync

    allowlist = json.dumps(["state.apply", "cmd.run", "disk.usage"])
    denylist = json.dumps([])
    db = _make_dual_db(allowlist, denylist)

    result = get_allowed_salt_functions_sync(db)

    for fn in ["state.apply", "cmd.run", "disk.usage"]:
        assert fn in result, f"'{fn}' should be allowed when denylist is empty"


def test_get_denied_falls_back_on_invalid_json():
    """Corrupted deny list DB value must not crash — return empty frozenset."""
    _reset_deny_cache()
    from fleet_platform.services.platform_settings_svc import get_denied_salt_functions_sync

    db = _make_db("not-valid-json{{")
    result = get_denied_salt_functions_sync(db)

    assert result == frozenset(), f"Expected empty frozenset on bad JSON, got {result}"
