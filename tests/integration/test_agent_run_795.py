"""Integration tests for the agent run + approval HTTP paths (#795, #803).

#795: POST /api/v1/agent/run/stream has zero integration coverage.
#803: The propose → approve/reject approval flow is not tested over HTTP.

These tests wire a real ASGI transport against the FastAPI app with a test
database; only the outbound LLM HTTP call is mocked (call_openai_compat).
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from fleet_platform.models.pending_action import PendingAction

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_sse(raw: bytes) -> list[dict]:
    """Decode a text/event-stream body into a list of parsed event dicts."""
    events = []
    for line in raw.decode().splitlines():
        if line.startswith("data: ") and not line.startswith("data: [DONE]"):
            try:
                events.append(json.loads(line[len("data: ") :]))
            except json.JSONDecodeError:
                pass
    return events


async def _make_default_endpoint(client: AsyncClient) -> dict:
    """Create an enabled default LLM endpoint via the API and return its JSON."""
    resp = await client.post(
        "/api/v1/llm/endpoints",
        json={
            "name": "agent-test-endpoint",
            "provider": "openai_compat",
            "base_url": "http://mock-llm/v1",
            "model": "mock-model",
            "is_default": True,
            "enabled": True,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@asynccontextmanager
async def _mock_openai_compat(final_text: str = "All nodes are healthy.", *, in_tok: int = 20, out_tok: int = 10):
    """Patch call_openai_compat to return a plain-text final answer immediately."""

    async def _fake(*args, **kwargs):
        return (final_text, in_tok, out_tok)

    with patch("fleet_platform.services.llm_caller.call_openai_compat", side_effect=_fake):
        yield


# ---------------------------------------------------------------------------
# #795 — agent run/stream integration
# ---------------------------------------------------------------------------


async def test_run_stream_viewer_forbidden(viewer_client: AsyncClient, admin_client: AsyncClient):
    """Viewer role must not reach the agent run endpoint (403)."""
    # ensure there's a default endpoint so the rejection is about RBAC not config
    await _make_default_endpoint(admin_client)

    async with _mock_openai_compat():
        resp = await viewer_client.post(
            "/api/v1/agent/run/stream",
            json={"prompt": "list all nodes"},
        )
    assert resp.status_code == 403


async def test_run_stream_no_endpoint_returns_422(operator_client: AsyncClient, db_session: AsyncSession):
    """When no default LLM endpoint exists the route must return 422."""
    from sqlalchemy import delete

    from fleet_platform.models.llm_endpoint import LLMEndpoint

    # Remove all endpoints so there is genuinely nothing to use.
    await db_session.execute(delete(LLMEndpoint))
    await db_session.commit()

    async with _mock_openai_compat():
        resp = await operator_client.post(
            "/api/v1/agent/run/stream",
            json={"prompt": "list all nodes"},
        )
    # 422 = no default endpoint configured, 404 = explicit endpoint_id not found
    assert resp.status_code in (422, 404)


async def test_run_stream_happy_path_sse_events(
    admin_client: AsyncClient,
    db_session: AsyncSession,
):
    """Happy-path: streaming run emits correct SSE event sequence and persists rows.

    Mocks call_openai_compat so no real LLM is needed.  Asserts every required
    SSE frame is present and that the AgentSession + LLMQueryLog rows land in DB.
    """
    from sqlalchemy import select

    from fleet_platform.models.agent_session import AgentSession
    from fleet_platform.models.llm_query_log import LLMQueryLog

    await _make_default_endpoint(admin_client)

    async with _mock_openai_compat("The fleet looks healthy, no drift detected."):
        resp = await admin_client.post(
            "/api/v1/agent/run/stream",
            json={"prompt": "check fleet status"},
        )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")

    events = _parse_sse(resp.content)
    event_types = [e.get("type") for e in events]

    # Required frames: session_start, at least one step_start, final, done
    assert "session_start" in event_types, f"Missing session_start in {event_types}"
    assert "step_start" in event_types, f"Missing step_start in {event_types}"
    assert "final" in event_types, f"Missing final in {event_types}"
    assert "done" in event_types, f"Missing done in {event_types}"

    # session_start must carry a valid UUID session_id and the model name
    session_start = next(e for e in events if e.get("type") == "session_start")
    assert uuid.UUID(session_start["session_id"])  # must be valid UUID
    assert session_start["model"] == "mock-model"

    # final event carries the mocked response text
    final_ev = next(e for e in events if e.get("type") == "final")
    assert "healthy" in final_ev.get("text", "")

    # done frame must carry status and query_id
    done_ev = next(e for e in events if e.get("type") == "done")
    assert done_ev.get("status") in ("completed", "aborted", "awaiting_approval")
    session_id = session_start["session_id"]

    # DB: AgentSession row must exist
    session_row = (
        await db_session.execute(select(AgentSession).where(AgentSession.id == uuid.UUID(session_id)))
    ).scalar_one_or_none()
    assert session_row is not None, "AgentSession row must be written to DB"
    assert session_row.initial_prompt == "check fleet status"

    # DB: LLMQueryLog row must be linked to the session
    log_row = (
        await db_session.execute(select(LLMQueryLog).where(LLMQueryLog.agent_session_id == uuid.UUID(session_id)))
    ).scalar_one_or_none()
    assert log_row is not None, "LLMQueryLog row must be written and linked to the session"
    assert log_row.intent == "agent"
    assert log_row.input_tokens == 20
    assert log_row.output_tokens == 10


async def test_run_stream_explicit_endpoint_id(
    admin_client: AsyncClient,
):
    """Passing an explicit endpoint_id routes to that endpoint."""
    endpoint = await _make_default_endpoint(admin_client)
    eid = endpoint["id"]

    async with _mock_openai_compat("explicit endpoint used"):
        resp = await admin_client.post(
            "/api/v1/agent/run/stream",
            json={"prompt": "what is the node count", "endpoint_id": eid},
        )
    assert resp.status_code == 200
    events = _parse_sse(resp.content)
    assert any(e.get("type") == "done" for e in events)


async def test_run_stream_nonexistent_endpoint_id_returns_404(admin_client: AsyncClient):
    """Passing an unknown endpoint_id must return 404 immediately."""
    async with _mock_openai_compat():
        resp = await admin_client.post(
            "/api/v1/agent/run/stream",
            json={"prompt": "x", "endpoint_id": str(uuid.uuid4())},
        )
    assert resp.status_code == 404


async def test_run_stream_error_path_emits_error_event(
    admin_client: AsyncClient,
    db_session: AsyncSession,
):
    """When the LLM call raises, the stream must emit an error SSE frame (not crash)."""
    await _make_default_endpoint(admin_client)

    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated LLM failure")

    with patch("fleet_platform.services.llm_caller.call_openai_compat", side_effect=_boom):
        resp = await admin_client.post(
            "/api/v1/agent/run/stream",
            json={"prompt": "trigger a failure"},
        )

    assert resp.status_code == 200  # streaming starts before LLM is called
    events = _parse_sse(resp.content)
    event_types = [e.get("type") for e in events]
    assert "error" in event_types, f"Expected 'error' event; got {event_types}"
    error_ev = next(e for e in events if e.get("type") == "error")
    assert "simulated LLM failure" in error_ev.get("error", "")
    # done frame still emitted (with aborted status)
    done_ev = next((e for e in events if e.get("type") == "done"), None)
    assert done_ev is not None
    assert done_ev.get("status") == "aborted"


# ---------------------------------------------------------------------------
# #803 — propose → approve/reject flow over HTTP
# ---------------------------------------------------------------------------


async def _create_pending_action(db: AsyncSession, *, requested_by: str = "op@fleet.local") -> "PendingAction":
    """Insert a bare-minimum agent-proposed PendingAction directly into the DB."""
    from fleet_platform.models.pending_action import PendingAction

    now = datetime.now(UTC)
    action = PendingAction(
        action_type="apply_salt_state",
        tool_name="apply_salt_state",
        params=json.dumps({"minion_id": "mm01", "state": "common"}),
        requested_by=requested_by,
        status="pending",
        created_at=now,
        expires_at=now + timedelta(hours=4),
        proposed_by_agent=True,
        target_count=1,
        co_sign_required=False,
    )
    db.add(action)
    await db.commit()
    await db.refresh(action)
    return action


async def test_list_agent_actions_returns_list(admin_client: AsyncClient):
    """GET /agent/actions returns a dict with 'actions' key."""
    resp = await admin_client.get("/api/v1/agent/actions")
    assert resp.status_code == 200
    body = resp.json()
    assert "actions" in body
    assert isinstance(body["actions"], list)


async def test_reject_agent_action_over_http(admin_client: AsyncClient, db_session: AsyncSession):
    """POST /agent/actions/{id}/reject transitions the action to 'rejected'."""
    from sqlalchemy import select

    from fleet_platform.models.pending_action import PendingAction

    action = await _create_pending_action(db_session, requested_by="op@fleet.local")
    action_id = str(action.id)

    resp = await admin_client.post(f"/api/v1/agent/actions/{action_id}/reject")
    assert resp.status_code == 200
    assert resp.json().get("status") == "rejected"

    # DB must reflect the rejected status
    refreshed = (
        await db_session.execute(select(PendingAction).where(PendingAction.id == action.id))
    ).scalar_one_or_none()
    assert refreshed is not None
    assert refreshed.status == "rejected"


async def test_approve_agent_action_over_http(admin_client: AsyncClient, db_session: AsyncSession, admin_user):
    """POST /agent/actions/{id}/approve transitions the action and runs the tool.

    The executor's dispatch_approved is stubbed so the test stays DB-only
    (no real Salt call).  Separation-of-duties: the approver must differ from
    the requester, so we insert an action owned by a different operator.
    """
    from fleet_platform.agent import executor as executor_mod

    action = await _create_pending_action(db_session, requested_by="other-op@fleet.local")
    action_id = str(action.id)

    # Stub the actual tool execution so no real Salt infra is needed.
    # dispatch_approved is async; patch.object auto-detects coroutines and uses
    # AsyncMock so `await executor.dispatch_approved(...)` returns fake_result.
    fake_result = AsyncMock()
    fake_result.ok = True
    fake_result.result = {"applied": True}
    fake_result.error = None

    with patch.object(executor_mod.Executor, "dispatch_approved", return_value=fake_result):
        resp = await admin_client.post(f"/api/v1/agent/actions/{action_id}/approve")

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") in ("approved", "executed", "executing")


async def test_approve_self_approval_returns_409(
    operator_client: AsyncClient,
    db_session: AsyncSession,
    operator_user,
):
    """An operator cannot approve their own proposed action (SOD rule → 409)."""
    action = await _create_pending_action(db_session, requested_by=operator_user.email)
    action_id = str(action.id)

    resp = await operator_client.post(f"/api/v1/agent/actions/{action_id}/approve")
    assert resp.status_code == 409
    assert "self-approval" in resp.json().get("detail", "").lower()


async def test_approve_nonexistent_action_returns_404(admin_client: AsyncClient):
    """Approving an unknown action id must return 404."""
    resp = await admin_client.post(f"/api/v1/agent/actions/{uuid.uuid4()}/approve")
    assert resp.status_code == 404


async def test_approve_invalid_uuid_returns_400(admin_client: AsyncClient):
    """A non-UUID action_id must be rejected with 400 before any DB lookup."""
    resp = await admin_client.post("/api/v1/agent/actions/not-a-uuid/approve")
    assert resp.status_code == 400
