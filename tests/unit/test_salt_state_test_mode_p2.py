"""Tests for the Salt state.apply dry-run (test=True) toggle (P2).

Verifies the wire contract end-to-end at the worker layer:
- ``test=True`` is forwarded as a kwarg on the salt-api dispatch
- The result status is ``ok_test`` (not ``ok``) so the UI can render a
  "Dry-run completed — no changes applied" banner instead of the green
  success state
- ``test=False`` (the default) is unchanged
- Pillar data and test=True compose into a single kwarg dict
"""
from __future__ import annotations

from unittest.mock import patch


def _master_creds() -> dict:
    return {
        "api_url": "http://salt-master:8080",
        "api_user": "kri",
        "api_password": "secret",
        "api_eauth": "pam",
        "tls_verify": True,
    }


def _captured_kwarg(mock_call):
    """Pull the kwarg= value passed to _run_salt_api from a single mock call."""
    return mock_call.call_args.kwargs.get("kwarg")


def test_apply_salt_state_default_does_not_set_test_kwarg():
    """Without test_mode the kwarg dict is None — backward compatibility."""
    from fleet_platform.workers.salt_tasks import apply_salt_state

    with (
        patch(
            "fleet_platform.workers.salt_tasks._get_default_master",
            return_value=_master_creds(),
        ),
        patch(
            "fleet_platform.workers.salt_tasks._run_salt_api",
            return_value={"status": "ok", "result": [{"web1": {}}]},
        ) as mock_run,
    ):
        result = apply_salt_state.run(
            state_name="nginx.install",
            target_minions=["web1"],
        )

    assert _captured_kwarg(mock_run) is None
    assert result["status"] == "ok"
    assert "test" not in result


def test_apply_salt_state_with_test_mode_sets_test_kwarg_and_status():
    """test_mode=True yields kwarg={'test': True} and status='ok_test'."""
    from fleet_platform.workers.salt_tasks import apply_salt_state

    with (
        patch(
            "fleet_platform.workers.salt_tasks._get_default_master",
            return_value=_master_creds(),
        ),
        patch(
            "fleet_platform.workers.salt_tasks._run_salt_api",
            return_value={"status": "ok", "result": [{"web1": {}}]},
        ) as mock_run,
    ):
        result = apply_salt_state.run(
            state_name="nginx.install",
            target_minions=["web1"],
            test_mode=True,
        )

    assert _captured_kwarg(mock_run) == {"test": True}
    # The bridge from salt-api 'ok' → 'ok_test' is what allows the UI
    # to distinguish a successful dry-run from a real apply.
    assert result["status"] == "ok_test"
    assert result["test"] is True


def test_apply_salt_state_test_mode_with_pillar_composes_kwargs():
    """Pillar + test=True share a single kwarg dict — neither overrides the other."""
    from fleet_platform.workers.salt_tasks import apply_salt_state

    with (
        patch(
            "fleet_platform.workers.salt_tasks._get_default_master",
            return_value=_master_creds(),
        ),
        patch(
            "fleet_platform.workers.salt_tasks._run_salt_api",
            return_value={"status": "ok", "result": []},
        ) as mock_run,
    ):
        apply_salt_state.run(
            state_name="app.deploy",
            target_minions=["web1", "web2"],
            pillar_data={"version": "1.2.3"},
            test_mode=True,
        )

    assert _captured_kwarg(mock_run) == {"pillar": {"version": "1.2.3"}, "test": True}


def test_apply_salt_state_test_mode_does_not_rewrite_error_status():
    """An upstream error must not be reported as a successful dry-run."""
    from fleet_platform.workers.salt_tasks import apply_salt_state

    with (
        patch(
            "fleet_platform.workers.salt_tasks._get_default_master",
            return_value=_master_creds(),
        ),
        patch(
            "fleet_platform.workers.salt_tasks._run_salt_api",
            return_value={"status": "error", "reason": "salt-api 401"},
        ),
    ):
        result = apply_salt_state.run(
            state_name="nginx.install",
            target_minions=["web1"],
            test_mode=True,
        )

    # Only an "ok" → "ok_test" rewrite happens; errors stay errors.
    assert result["status"] == "error"
    assert result.get("reason") == "salt-api 401"
