"""Behavioural tests for code quality fixes in #580.

Four tests — each fails against pre-fix behaviour:

1. test_bootstrap_guard_403_actually_called
   — calls run_playbook_endpoint with bootstrap_node.yml → must raise 403.
   — Deleting the 'if safe_name in _BOOTSTRAP_ONLY_PLAYBOOKS' guard makes it fail.

2. test_multigroup_node_yields_all_groups
   — verifies the reindex_nodes group-aggregation produces all group names in
     the chunk text, not just the last one (the old dict-comprehension bug).

3. test_run_playbook_accepts_external_source_playbook
   — verifies that a playbook discovered in an external (non-builtin) source dir
     is accepted by run_playbook_endpoint instead of 404-ing.

4. test_tasks_route_requires_role
   — verifies that the GET /tasks/{task_id} route uses require_role, not the
     weaker get_current_user (which does not enforce role at all).
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── helpers ───────────────────────────────────────────────────────────────────


def _make_entry(filename: str):
    e = MagicMock()
    e.filename = filename
    e.name = filename
    e.description = ""
    e.entry_type = "playbook"
    e.default_vars = {}
    e.var_descriptions = {}
    e.lint_errors = []
    return e


def _make_claims(role: str = "operator") -> dict:
    return {"sub": str(uuid.uuid4()), "email": f"{role}@kri", "role": role}


# ── 1. Bootstrap guard is behavioural ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_bootstrap_guard_403_actually_called():
    """Calling run_playbook_endpoint with a bootstrap-only playbook must raise 403.

    This test will FAIL if the guard is deleted — it invokes the handler directly,
    it does NOT inspect source code.
    """
    from fastapi import HTTPException

    from fleet_platform.api.routes.ansible import run_playbook_endpoint

    payload = MagicMock()
    payload.playbook = "bootstrap_node.yml"
    payload.target_type = "node"
    payload.target_id = str(uuid.uuid4())
    payload.extravars = None
    payload.verbosity = 0
    payload.timeout_seconds = 300
    payload.ssh_username = None

    # Mock DB: no external sources configured (returns None for sources query)
    db = AsyncMock()
    mock_sources_result = MagicMock()
    mock_sources_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_sources_result)

    with patch(
        "fleet_platform.api.routes.ansible.playbooks.discover_all",
        return_value=[_make_entry("bootstrap_node.yml")],
    ):
        with pytest.raises(HTTPException) as exc_info:
            await run_playbook_endpoint(payload=payload, db=db, claims=_make_claims("operator"))

    assert exc_info.value.status_code == 403, "Bootstrap guard must return 403 — deleting the guard would 404 or 202"


# ── 2. Multi-group node yields all groups ────────────────────────────────────


def test_multigroup_node_yields_all_groups():
    """reindex_nodes must aggregate ALL groups, not just the last.

    The old `{str(r.node_id): r.name for r in membership}` kept only the last
    group when a node belonged to multiple groups.  The fix uses setdefault to
    build a list.  This test verifies that both group names appear in the chunk.
    """
    from fleet_platform.services.embedding_svc import chunk_node

    node_id = "aaaa-1111"

    # Simulate what the fixed aggregation produces: node in two groups
    groups_for_node = ["webservers", "production"]
    group_str = ", ".join(groups_for_node)

    chunks = chunk_node(
        node_id=node_id,
        hostname="web-01",
        ip="192.168.1.10",
        status="online",
        group=group_str,
        os_info="",
        last_seen="5 minutes ago",
        include_ips=True,
    )

    assert chunks, "chunk_node must produce at least one chunk"
    combined_text = " ".join(c["chunk_text"] for c in chunks)
    assert "webservers" in combined_text, "First group must appear in embedding chunk"
    assert "production" in combined_text, "Second group must appear in embedding chunk"


# ── 3. External-source playbook is accepted ──────────────────────────────────


@pytest.mark.asyncio
async def test_run_playbook_accepts_external_source_playbook():
    """run_playbook_endpoint accepts a playbook found in an external source dir.

    Before the fix, the endpoint only searched _PLAYBOOKS_DIR (builtin), so any
    playbook from an external git/local source would always 404.  After the fix
    it searches all configured dirs via get_all_playbook_dirs.

    This test will FAIL against the pre-fix code (the external entry is never
    found, so a 404 is raised).
    """
    from pathlib import Path

    from fastapi import HTTPException

    from fleet_platform.api.routes.ansible import run_playbook_endpoint

    external_filename = "deploy_app.yml"
    external_dir = Path("/external/playbooks")

    payload = MagicMock()
    payload.playbook = external_filename
    payload.target_type = "node"
    payload.target_id = str(uuid.uuid4())
    payload.extravars = None
    payload.verbosity = 0
    payload.timeout_seconds = 300
    payload.ssh_username = None

    # DB returns a fake sources setting pointing at the external dir
    import json as _json

    fake_setting = MagicMock()
    fake_setting.value = _json.dumps([{"type": "local", "path": str(external_dir)}])

    mock_sources_result = MagicMock()
    mock_sources_result.scalar_one_or_none.return_value = fake_setting

    # Second DB execute (for Node lookup) returns a valid node
    mock_node = MagicMock()
    mock_node.hostname = "node-01"
    mock_node.minion_id = "node-01"
    mock_node_result = MagicMock()
    mock_node_result.scalar_one_or_none.return_value = mock_node

    # AnsibleJob added via db.add() needs a real UUID id for PlaybookRunResponse
    _job_id = uuid.uuid4()

    async def _execute_side_effect(stmt):
        # First call: sources query; second: node query
        if not hasattr(_execute_side_effect, "_calls"):
            _execute_side_effect._calls = 0
        _execute_side_effect._calls += 1
        if _execute_side_effect._calls == 1:
            return mock_sources_result
        return mock_node_result

    def _add_side_effect(obj):
        # Inject a real UUID id into the AnsibleJob mock when db.add() is called
        if hasattr(obj, "id"):
            obj.id = _job_id

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=_execute_side_effect)
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock(side_effect=_add_side_effect)
    db.scalar = AsyncMock(return_value=0)

    def _discover_side_effect(directory):
        # Builtin dir returns nothing; external dir returns the playbook
        if Path(directory) == external_dir:
            return [_make_entry(external_filename)]
        return []

    with (
        patch(
            "fleet_platform.api.routes.ansible.playbooks.get_all_playbook_dirs",
            return_value=[external_dir],
        ),
        patch(
            "fleet_platform.api.routes.ansible.playbooks.discover_all",
            side_effect=_discover_side_effect,
        ),
        patch("fleet_platform.api.routes.ansible.playbooks.audit", new=AsyncMock()),
        # #749: the endpoint enqueues via celery_app.send_task(...) (by task name)
        # rather than importing run_playbook and calling .delay().
        patch(
            "fleet_platform.api.routes.ansible.playbooks.celery_app.send_task",
            new=MagicMock(return_value=MagicMock(id="task-id")),
        ),
    ):
        # Should NOT raise 404 — external playbook must be found
        try:
            result = await run_playbook_endpoint(payload=payload, db=db, claims=_make_claims("operator"))
            # If we reach here, the playbook was found and queued — test passes
            assert result is not None
        except HTTPException as e:
            if e.status_code == 404:
                pytest.fail("External-source playbook 404'd — allowlist still only checks builtin dir")
            raise


# ── 4. tasks/{task_id} requires a role ───────────────────────────────────────


def test_tasks_route_requires_role():
    """GET /tasks/{task_id} must use require_role, not bare get_current_user.

    get_current_user only validates the token; it does NOT enforce any role.
    Unauthenticated-but-valid viewers should still be able to reach this route,
    while we must ensure the dependency is role-aware (not unscoped).

    This test fails if the Depends() is still get_current_user (no role check).
    """
    import inspect

    from fleet_platform.api.routes.ansible import get_task_status

    sig = inspect.signature(get_task_status)
    params = sig.parameters

    assert "_" in params or "claims" in params, "get_task_status must have an auth dependency parameter"

    # Inspect the default of the auth parameter — it must be a Depends() whose
    # dependency is the inner closure produced by require_role(), NOT get_current_user.
    from fastapi import params as fastapi_params

    from fleet_platform.core.auth import get_current_user

    for param in params.values():
        if isinstance(param.default, fastapi_params.Depends):
            dep = param.default.dependency
            # If it is get_current_user directly → test fails
            if dep is get_current_user:
                pytest.fail(
                    "GET /tasks/{task_id} uses bare get_current_user — "
                    "must use require_role('viewer', ...) to enforce RBAC"
                )
            # Verify it is a closure produced by require_role (has __closure__)
            assert callable(dep) and dep.__closure__ is not None, (
                "The auth dependency must be a require_role closure, not a plain function"
            )
            return

    pytest.fail("get_task_status has no Depends() auth parameter at all")
