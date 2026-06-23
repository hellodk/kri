"""
Tests for #840 Issue B — LLM endpoint enable/disable toggle.

Source-contract + functional style:
- Parses llm.py and llm_svc.py for structural guarantees.
- Tests update_endpoint logic in-process with a lightweight fake DB session.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

LLM_ROUTE = Path("fleet_platform/api/routes/llm.py").read_text()
LLM_SVC = Path("fleet_platform/services/llm_svc.py").read_text()

# ---------------------------------------------------------------------------
# Source-contract: audit log includes enabled old→new
# ---------------------------------------------------------------------------


def test_audit_includes_enabled_field():
    """Route must record enabled old→new in the audit payload on update."""
    assert '"enabled"' in LLM_ROUTE or "'enabled'" in LLM_ROUTE, (
        "audit payload in update_endpoint route does not reference 'enabled'"
    )


def test_audit_captures_old_enabled_before_update():
    """old_enabled must be captured before update_endpoint is called."""
    route_update_fn_start = LLM_ROUTE.index("async def update_endpoint(")
    route_update_fn_end = LLM_ROUTE.index("\n\n@router", route_update_fn_start)
    fn_body = LLM_ROUTE[route_update_fn_start:route_update_fn_end]

    old_enabled_pos = fn_body.find("old_enabled")
    update_call_pos = fn_body.find("await llm_svc.update_endpoint(")
    audit_call_pos = fn_body.find("await audit(")

    assert old_enabled_pos != -1, "old_enabled not captured in update_endpoint route"
    assert old_enabled_pos < update_call_pos, (
        "old_enabled must be captured BEFORE update_endpoint() to record the previous value"
    )
    assert audit_call_pos > update_call_pos, "audit() must be called AFTER update_endpoint()"


def test_audit_records_old_and_new_enabled():
    """audit_value dict must include both old and new enabled values."""
    assert '{"old": old_enabled, "new": endpoint.enabled}' in LLM_ROUTE or (
        '"old"' in LLM_ROUTE and '"new"' in LLM_ROUTE and "old_enabled" in LLM_ROUTE
    ), "audit log must record both old and new enabled values"


# ---------------------------------------------------------------------------
# Source-contract: llm_svc clears is_default when endpoint is disabled
# ---------------------------------------------------------------------------


def test_svc_clears_is_default_on_disable():
    """update_endpoint service must clear is_default when enabled is set to False."""
    assert "not payload.enabled and endpoint.is_default" in LLM_SVC or (
        "not payload.enabled" in LLM_SVC and "is_default = False" in LLM_SVC
    ), "llm_svc.update_endpoint must clear is_default when disabling an endpoint"


def test_svc_does_not_clear_is_default_on_enable():
    """Enabling an endpoint must NOT touch is_default."""
    svc_fn_start = LLM_SVC.index("async def update_endpoint(")
    svc_fn_end = LLM_SVC.index("\nasync def delete_endpoint", svc_fn_start)
    fn_body = LLM_SVC[svc_fn_start:svc_fn_end]

    # The is_default = False assignment inside the enabled block must be
    # guarded by `not payload.enabled`
    assert re.search(r"not payload\.enabled.*is_default\s*=\s*False", fn_body, re.DOTALL), (
        "is_default = False must be inside a 'not payload.enabled' guard"
    )


# ---------------------------------------------------------------------------
# Functional: update_endpoint in-process logic
# ---------------------------------------------------------------------------


def _make_endpoint(**kwargs) -> MagicMock:
    ep = MagicMock()
    ep.id = uuid.uuid4()
    ep.name = kwargs.get("name", "test-ep")
    ep.provider = kwargs.get("provider", "openai_compat")
    ep.base_url = kwargs.get("base_url", "http://localhost:11434")
    ep.api_key_encrypted = None
    ep.model = kwargs.get("model", "gpt-4o")
    ep.max_tokens = kwargs.get("max_tokens", 4096)
    ep.is_default = kwargs.get("is_default", False)
    ep.enabled = kwargs.get("enabled", True)
    ep.model_context_length = None
    ep.model_capabilities = None
    ep.tool_mode = "json"
    return ep


@pytest.mark.asyncio
async def test_disable_endpoint_clears_is_default():
    """Disabling a default endpoint must set is_default=False."""
    from fleet_platform.schemas.llm import LLMEndpointUpdate
    from fleet_platform.services import llm_svc

    ep = _make_endpoint(is_default=True, enabled=True)

    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    payload = LLMEndpointUpdate(enabled=False)

    await llm_svc.update_endpoint(db, ep, payload)

    assert ep.enabled is False, "endpoint.enabled must be False after disable"
    assert ep.is_default is False, "endpoint.is_default must be cleared when endpoint is disabled"


@pytest.mark.asyncio
async def test_disable_non_default_endpoint_leaves_is_default_untouched():
    """Disabling a non-default endpoint must not change is_default."""
    from fleet_platform.schemas.llm import LLMEndpointUpdate
    from fleet_platform.services import llm_svc

    ep = _make_endpoint(is_default=False, enabled=True)

    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    payload = LLMEndpointUpdate(enabled=False)

    await llm_svc.update_endpoint(db, ep, payload)

    assert ep.enabled is False
    assert ep.is_default is False, "is_default was already False and must stay False"


@pytest.mark.asyncio
async def test_enable_endpoint_does_not_set_is_default():
    """Enabling a disabled endpoint must NOT automatically set is_default."""
    from fleet_platform.schemas.llm import LLMEndpointUpdate
    from fleet_platform.services import llm_svc

    ep = _make_endpoint(is_default=False, enabled=False)

    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    payload = LLMEndpointUpdate(enabled=True)

    await llm_svc.update_endpoint(db, ep, payload)

    assert ep.enabled is True
    assert ep.is_default is False, "enabling an endpoint must not auto-set is_default"
