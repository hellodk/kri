"""Regression tests for webssh.py security fixes (issues #85)."""

import inspect

from fastapi import params as fa_params


def _has_require_role_dep(fn) -> bool:
    """Return True if fn has at least one Depends that is a require_role(...) closure.

    require_role(*roles) returns an inner async function whose __qualname__ ends in
    'require_role.<locals>.dependency' and whose closure captures a set of permitted
    role strings.
    """
    sig = inspect.signature(fn)
    for param in sig.parameters.values():
        if isinstance(param.default, fa_params.Depends):
            dep = param.default.dependency
            if getattr(dep, "__qualname__", "").endswith("require_role.<locals>.dependency"):
                if hasattr(dep, "__closure__") and dep.__closure__:
                    for cell in dep.__closure__:
                        try:
                            val = cell.cell_contents
                            if isinstance(val, set) and val:
                                return True
                        except ValueError:
                            pass
    return False


def test_session_list_requires_role():
    """list_sessions must use require_role (not get_current_user) — #85."""
    from fleet_platform.api.routes.webssh import list_sessions

    assert _has_require_role_dep(list_sessions), "list_sessions must use require_role, not get_current_user"


def test_session_recording_requires_role():
    """get_session_recording must use require_role — #85."""
    from fleet_platform.api.routes.webssh import get_session_recording

    assert _has_require_role_dep(get_session_recording), "get_session_recording must use require_role"


def test_security_events_requires_role():
    """list_security_events must use require_role — #85."""
    from fleet_platform.api.routes.webssh import list_security_events

    assert _has_require_role_dep(list_security_events), "list_security_events must use require_role"
