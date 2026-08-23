import json
import logging
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.api.limiter import limiter
from fleet_platform.core.audit import audit
from fleet_platform.core.auth import require_role
from fleet_platform.schemas.llm import (
    DiscoveredModel,
    LLMEndpointCreate,
    LLMEndpointResponse,
    LLMEndpointTestResponse,
    LLMEndpointUpdate,
    LLMQueryLogEntry,
    LLMQueryRequest,
    LLMQueryResponse,
)
from fleet_platform.services import llm_svc
from fleet_platform.services.llm_caller import (
    LLMCallError,
    call_anthropic,
    call_openai_compat,
    stream_anthropic,
    stream_openai_compat,
)
from fleet_platform.services.llm_context import build_fleet_context
from fleet_platform.services.model_catalog import get_models
from fleet_platform.services.model_discovery import discover_models_with_health
from fleet_platform.services.prompt_safety import sanitize_llm_output

router = APIRouter(prefix="/api/v1/llm", tags=["llm"])

logger = logging.getLogger(__name__)


async def _resolve_model(endpoint) -> str:
    """Resolve '__auto__' to a concrete model id at query dispatch time.

    For non-auto endpoints returns endpoint.model unchanged.
    For __auto__ picks lowest-latency healthy model from cache,
    re-probing if stale. Raises HTTP 503 if no healthy model found.
    """
    from fleet_platform.services import model_health_cache as hc
    from fleet_platform.services.llm_svc import get_decrypted_api_key
    from fleet_platform.services.model_discovery import discover_models_with_health

    if endpoint.model != "__auto__":
        return endpoint.model

    url = endpoint.base_url or ""
    provider = endpoint.provider

    if hc.is_stale(url, provider):
        api_key = get_decrypted_api_key(endpoint)
        await discover_models_with_health(url, provider, api_key=api_key)

    healthy = hc.get_healthy_models(url, provider)
    if not healthy:
        raise HTTPException(
            status_code=503,
            detail=f"No healthy models available on endpoint '{endpoint.name}'. "
            "Refresh model status or check the endpoint URL.",
        )
    return healthy[0]["id"]


@router.get("/models")
async def list_models(
    provider: str | None = None,
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    """Return the shared model catalog, optionally filtered by provider.

    Used by the UI model selector dropdown.
    """
    return get_models(provider)


class DiscoverModelsRequest(BaseModel):
    url: str
    provider: str


@router.post("/discover-models")
async def discover_endpoint_models(
    req: DiscoverModelsRequest,
    _: dict = Depends(require_role("operator", "admin")),
):
    """Query a provider endpoint, probe health, and return available models."""
    models = await discover_models_with_health(req.url, req.provider, api_key=None)
    return {"models": [DiscoveredModel(**m) for m in models]}


def _to_response(endpoint) -> LLMEndpointResponse:
    return LLMEndpointResponse(
        id=endpoint.id,
        name=endpoint.name,
        provider=endpoint.provider,
        base_url=endpoint.base_url,
        has_api_key=endpoint.api_key_encrypted is not None,
        model=endpoint.model,
        max_tokens=endpoint.max_tokens,
        is_default=endpoint.is_default,
        enabled=endpoint.enabled,
        created_at=endpoint.created_at,
        updated_at=endpoint.updated_at,
        model_context_length=endpoint.model_context_length,
        model_capabilities=(
            [c.strip() for c in endpoint.model_capabilities.split(",") if c.strip()]
            if endpoint.model_capabilities
            else []
        ),
        tool_mode=endpoint.tool_mode,
    )


# -- Endpoint management (admin only) -----------------------------------------


@router.get("/endpoints", response_model=list[LLMEndpointResponse])
async def list_endpoints(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    endpoints = await llm_svc.list_endpoints(db)
    return [_to_response(e) for e in endpoints]


@router.post("/endpoints", response_model=LLMEndpointResponse, status_code=201)
async def create_endpoint(
    payload: LLMEndpointCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("admin")),
):
    endpoint = await llm_svc.create_endpoint(db, payload)
    await audit(
        db,
        actor=claims["email"],
        action="llm_endpoint.create",
        resource_type="llm_endpoint",
        resource_id=endpoint.id,
        new_value={"name": endpoint.name, "provider": endpoint.provider, "model": endpoint.model},
    )
    await db.commit()
    return _to_response(endpoint)


@router.get("/endpoints/{endpoint_id}", response_model=LLMEndpointResponse)
async def get_endpoint(
    endpoint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    endpoint = await llm_svc.get_endpoint(db, endpoint_id)
    if not endpoint:
        raise HTTPException(status_code=404, detail="LLM endpoint not found")
    return _to_response(endpoint)


@router.put("/endpoints/{endpoint_id}", response_model=LLMEndpointResponse)
async def update_endpoint(
    endpoint_id: uuid.UUID,
    payload: LLMEndpointUpdate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("admin")),
):
    endpoint = await llm_svc.get_endpoint(db, endpoint_id)
    if not endpoint:
        raise HTTPException(status_code=404, detail="LLM endpoint not found")
    old_enabled = endpoint.enabled
    old_is_default = endpoint.is_default
    endpoint = await llm_svc.update_endpoint(db, endpoint, payload)
    audit_value: dict = {"name": endpoint.name, "provider": endpoint.provider, "model": endpoint.model}
    if payload.enabled is not None and payload.enabled != old_enabled:
        audit_value["enabled"] = {"old": old_enabled, "new": endpoint.enabled}
    if endpoint.is_default != old_is_default:
        audit_value["is_default"] = {"old": old_is_default, "new": endpoint.is_default}
    await audit(
        db,
        actor=claims["email"],
        action="llm_endpoint.update",
        resource_type="llm_endpoint",
        resource_id=endpoint_id,
        new_value=audit_value,
    )
    await db.commit()
    return _to_response(endpoint)


@router.delete("/endpoints/{endpoint_id}", status_code=204)
async def delete_endpoint(
    endpoint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("admin")),
):
    endpoint = await llm_svc.get_endpoint(db, endpoint_id)
    if not endpoint:
        raise HTTPException(status_code=404, detail="LLM endpoint not found")
    await audit(
        db,
        actor=claims["email"],
        action="llm_endpoint.delete",
        resource_type="llm_endpoint",
        resource_id=endpoint_id,
        new_value={"name": endpoint.name, "provider": endpoint.provider},
    )
    await llm_svc.delete_endpoint(db, endpoint)


@router.post("/endpoints/{endpoint_id}/test", response_model=LLMEndpointTestResponse)
async def test_endpoint(
    endpoint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    endpoint = await llm_svc.get_endpoint(db, endpoint_id)
    if not endpoint:
        raise HTTPException(status_code=404, detail="LLM endpoint not found")

    api_key = llm_svc.get_decrypted_api_key(endpoint)
    ping_prompt = "Reply with exactly one word: hello"
    # Reasoning models (e.g. Qwen3/DeepSeek on mlx-lm) emit a few hundred tokens
    # of chain-of-thought before any answer. A tiny budget gets fully consumed by
    # thinking, leaving empty content and falsely flagging a healthy endpoint as
    # broken — so give the probe enough room to clear the preamble (#probe).
    _PROBE_MAX_TOKENS = 256
    t0 = time.perf_counter()
    try:
        if endpoint.provider == "anthropic":
            await call_anthropic(
                api_key=api_key or "",
                model=endpoint.model,
                max_tokens=_PROBE_MAX_TOKENS,
                system_prompt="You are a test probe.",
                user_prompt=ping_prompt,
            )
        else:
            await call_openai_compat(
                base_url=endpoint.base_url,
                api_key=api_key,
                model=endpoint.model,
                max_tokens=_PROBE_MAX_TOKENS,
                system_prompt="You are a test probe.",
                user_prompt=ping_prompt,
            )
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return LLMEndpointTestResponse(ok=True, latency_ms=latency_ms)
    except (LLMCallError, Exception) as exc:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return LLMEndpointTestResponse(ok=False, latency_ms=latency_ms, error=str(exc))


# -- Query (operator+) --------------------------------------------------------


@router.post("/query", response_model=LLMQueryResponse)
@limiter.limit("10/minute")
async def submit_query(
    request: Request,
    payload: LLMQueryRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    if payload.endpoint_id:
        endpoint = await llm_svc.get_endpoint(db, payload.endpoint_id)
        if not endpoint:
            raise HTTPException(status_code=404, detail="LLM endpoint not found")
    else:
        endpoint = await llm_svc.get_default_endpoint(db)
        if not endpoint:
            raise HTTPException(
                status_code=422,
                detail="No default LLM endpoint configured. Add one in Settings -> LLM.",
            )

    if not endpoint.enabled:
        raise HTTPException(status_code=422, detail="Selected LLM endpoint is disabled")

    api_key = llm_svc.get_decrypted_api_key(endpoint)
    model_ctx = endpoint.model_context_length
    model_caps = (
        [c.strip() for c in endpoint.model_capabilities.split(",") if c.strip()] if endpoint.model_capabilities else []
    )

    # Resolve 'auto' intent via heuristic classifier before building context
    resolved_intent: str = payload.intent
    if payload.intent == "auto":
        from fleet_platform.services.llm_intent import classify_intent

        resolved_intent = classify_intent(payload.prompt)
    intent = resolved_intent

    rag_citations: list[dict] = []
    try:
        system_prompt, rag_citations = await build_fleet_context(db, intent, query=payload.prompt)
    except Exception:  # noqa: BLE001
        logger.exception("submit_query: build_fleet_context failed; degrading to minimal context")
        system_prompt = (
            "You are an AI assistant embedded in kri, a fleet management platform. "
            "Live fleet context could not be loaded for this query; answer from general knowledge "
            "and tell the operator the fleet context was temporarily unavailable."
        )

    history_dicts: list[dict] = (
        [{"role": m.role, "content": m.content} for m in payload.history] if payload.history else []
    )

    # Enforce a 6000-token total history budget — drop oldest turns first.
    # Rough estimate: 1 token ≈ 4 chars.
    _HISTORY_TOKEN_BUDGET = 6000
    total_chars = sum(len(m["content"]) for m in history_dicts)
    while history_dicts and total_chars > _HISTORY_TOKEN_BUDGET * 4:
        removed = history_dicts.pop(0)
        total_chars -= len(removed["content"])

    chosen_model = await _resolve_model(endpoint)

    t0 = time.perf_counter()
    error: str | None = None
    content: str = ""
    input_tokens = 0
    output_tokens = 0

    try:
        if endpoint.provider == "anthropic":
            content, input_tokens, output_tokens = await call_anthropic(
                api_key=api_key or "",
                model=chosen_model,
                max_tokens=endpoint.max_tokens,
                system_prompt=system_prompt,
                user_prompt=payload.prompt,
                history=history_dicts,
            )
        else:
            content, input_tokens, output_tokens = await call_openai_compat(
                base_url=endpoint.base_url,
                api_key=api_key,
                model=chosen_model,
                max_tokens=endpoint.max_tokens,
                system_prompt=system_prompt,
                user_prompt=payload.prompt,
                history=history_dicts,
                model_context_length=model_ctx,
                model_capabilities=model_caps,
            )
    except (LLMCallError, Exception) as exc:
        if endpoint.model == "__auto__":
            from fleet_platform.services import model_health_cache as hc

            hc.evict(endpoint.base_url or "", endpoint.provider, chosen_model)
            _fallback = hc.get_healthy_models(endpoint.base_url or "", endpoint.provider)
            if _fallback:
                chosen_model = _fallback[0]["id"]
                try:
                    if endpoint.provider == "anthropic":
                        content, input_tokens, output_tokens = await call_anthropic(
                            api_key=api_key or "",
                            model=chosen_model,
                            max_tokens=endpoint.max_tokens,
                            system_prompt=system_prompt,
                            user_prompt=payload.prompt,
                            history=history_dicts,
                        )
                    else:
                        content, input_tokens, output_tokens = await call_openai_compat(
                            base_url=endpoint.base_url,
                            api_key=api_key,
                            model=chosen_model,
                            max_tokens=endpoint.max_tokens,
                            system_prompt=system_prompt,
                            user_prompt=payload.prompt,
                            history=history_dicts,
                            model_context_length=model_ctx,
                            model_capabilities=model_caps,
                        )
                    error = None
                except (LLMCallError, Exception) as retry_exc:
                    hc.evict(endpoint.base_url or "", endpoint.provider, chosen_model)
                    error = str(retry_exc)
            else:
                error = str(exc)
        else:
            # Fixed-model endpoint: mark transiently unhealthy so it falls out
            # of rotation until a successful probe restores it (#840).
            # NEVER touch LLMEndpoint.enabled — that is operator-only.
            if isinstance(exc, LLMCallError):
                from fleet_platform.services import model_health_cache as hc

                hc.set_health(
                    endpoint.base_url or "",
                    endpoint.provider,
                    endpoint.model,
                    healthy=False,
                    latency_ms=None,
                )
            error = str(exc)

    duration_ms = int((time.perf_counter() - t0) * 1000)

    # Sanitize the complete model answer once at the API boundary (#782,
    # #1048): covers the response body (``result``) and the persisted log row.
    if content:
        content = sanitize_llm_output(content)

    log = await llm_svc.create_query_log(
        db,
        endpoint_id=endpoint.id,
        user_id=claims["sub"],
        intent=intent,  # resolved (auto → classified)
        prompt=payload.prompt,
        system_prompt=system_prompt,
        response=content or None,
        model_used=chosen_model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        duration_ms=duration_ms,
        error=error,
    )

    await audit(
        db,
        actor=claims["sub"],
        action="llm_query",
        resource_type="llm",
        resource_id=None,
        new_value={
            "query": payload.prompt[:200],
            "intent": intent,  # resolved (auto → classified)
            "model": chosen_model,
            "endpoint": endpoint.name,
        },
    )

    if error:
        raise HTTPException(status_code=502, detail=f"LLM call failed: {error}")

    return LLMQueryResponse(
        query_id=log.id,
        intent=intent,  # resolved (auto → classified)
        result=content,
        model_used=chosen_model,
        endpoint_name=endpoint.name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        duration_ms=duration_ms,
        citations=rag_citations,
    )


@router.get("/queries", response_model=list[LLMQueryLogEntry])
async def list_queries(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    logs = await llm_svc.list_query_logs(db, user_id=claims["sub"], limit=50)
    return [LLMQueryLogEntry.model_validate(log) for log in logs]


# ── Streaming query (operator+) ───────────────────────────────────────────────
# SSE stream that emits one JSON event per LLM token delta, then a `done`
# event with usage + the persisted query_id, then `[DONE]`. Browsers cannot
# POST through EventSource, so the frontend uses fetch + ReadableStream and
# parses SSE manually (see frontend/src/api/llmStream.ts).
#
# Event shapes (one per `data:` line):
#   {"type": "delta", "text": "<chunk>"}
#   {"type": "done",  "query_id": "<uuid>", "intent": "...", "model_used": "...",
#                     "endpoint_name": "...", "input_tokens": int,
#                     "output_tokens": int, "duration_ms": int}
#   {"type": "error", "error": "<message>"}


@router.post("/query/stream")
@limiter.limit("10/minute")
async def submit_query_stream(
    request: Request,
    payload: LLMQueryRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    """Stream the LLM response as Server-Sent Events.

    Mirrors :func:`submit_query` for endpoint resolution, intent classification,
    fleet-context building, and history budgeting; differs only in delivery.
    Persists the query log on completion (or on stream error) so the Queries
    listing reflects every attempt regardless of whether the client stayed
    connected.
    """
    if payload.endpoint_id:
        endpoint = await llm_svc.get_endpoint(db, payload.endpoint_id)
        if not endpoint:
            raise HTTPException(status_code=404, detail="LLM endpoint not found")
    else:
        endpoint = await llm_svc.get_default_endpoint(db)
        if not endpoint:
            raise HTTPException(
                status_code=422,
                detail="No default LLM endpoint configured. Add one in Settings -> LLM.",
            )

    if not endpoint.enabled:
        raise HTTPException(status_code=422, detail="Selected LLM endpoint is disabled")

    api_key = llm_svc.get_decrypted_api_key(endpoint)
    model_ctx = endpoint.model_context_length
    model_caps = (
        [c.strip() for c in endpoint.model_capabilities.split(",") if c.strip()] if endpoint.model_capabilities else []
    )

    resolved_intent: str = payload.intent
    if payload.intent == "auto":
        from fleet_platform.services.llm_intent import classify_intent

        resolved_intent = classify_intent(payload.prompt)
    intent = resolved_intent

    try:
        system_prompt, _stream_citations = await build_fleet_context(db, intent, query=payload.prompt)
    except Exception:  # noqa: BLE001
        logger.exception("submit_query_stream: build_fleet_context failed; degrading to minimal context")
        system_prompt = (
            "You are an AI assistant embedded in kri, a fleet management platform. "
            "Live fleet context could not be loaded for this query; answer from general knowledge "
            "and tell the operator the fleet context was temporarily unavailable."
        )
        _stream_citations = []

    history_dicts: list[dict] = (
        [{"role": m.role, "content": m.content} for m in payload.history] if payload.history else []
    )
    _HISTORY_TOKEN_BUDGET = 6000
    total_chars = sum(len(m["content"]) for m in history_dicts)
    while history_dicts and total_chars > _HISTORY_TOKEN_BUDGET * 4:
        removed = history_dicts.pop(0)
        total_chars -= len(removed["content"])

    chosen_model = await _resolve_model(endpoint)

    async def event_stream():
        t0 = time.perf_counter()
        joined_content = ""
        input_tokens = 0
        output_tokens = 0
        error: str | None = None

        try:
            if endpoint.provider == "anthropic":
                source = stream_anthropic(
                    api_key=api_key or "",
                    model=chosen_model,
                    max_tokens=endpoint.max_tokens,
                    system_prompt=system_prompt,
                    user_prompt=payload.prompt,
                    history=history_dicts,
                )
            else:
                source = stream_openai_compat(
                    base_url=endpoint.base_url,
                    api_key=api_key,
                    model=chosen_model,
                    max_tokens=endpoint.max_tokens,
                    system_prompt=system_prompt,
                    user_prompt=payload.prompt,
                    history=history_dicts,
                    model_context_length=model_ctx,
                    model_capabilities=model_caps,
                )

            async for event in source:
                etype = event.get("type")
                if etype == "delta":
                    yield f"data: {json.dumps(event)}\n\n"
                elif etype == "reasoning":
                    # Forward chain-of-thought on its own channel so the UI can
                    # render a live "thinking…" panel without it being persisted
                    # as the answer (#reasoning).
                    yield f"data: {json.dumps(event)}\n\n"
                elif etype == "error":
                    error = event.get("error") or "unknown error"
                    # Fixed-model endpoint: mark transiently unhealthy so it
                    # falls out of rotation until a probe restores it (#840).
                    # NEVER touch LLMEndpoint.enabled — operator-only.
                    if endpoint.model != "__auto__":
                        from fleet_platform.services import model_health_cache as _hc

                        _hc.set_health(
                            endpoint.base_url or "",
                            endpoint.provider,
                            endpoint.model,
                            healthy=False,
                            latency_ms=None,
                        )
                    yield f"data: {json.dumps(event)}\n\n"
                elif etype == "done":
                    joined_content = event.get("content", "")
                    input_tokens = int(event.get("input_tokens") or 0)
                    output_tokens = int(event.get("output_tokens") or 0)
        except Exception as exc:  # noqa: BLE001
            # Guard: any unexpected failure inside the generator must still
            # produce an SSE error frame so the client never hangs forever.
            error = f"stream failed: {exc}"
            if endpoint.model != "__auto__":
                from fleet_platform.services import model_health_cache as _hc

                _hc.set_health(
                    endpoint.base_url or "",
                    endpoint.provider,
                    endpoint.model,
                    healthy=False,
                    latency_ms=None,
                )
            yield f"data: {json.dumps({'type': 'error', 'error': error})}\n\n"

        duration_ms = int((time.perf_counter() - t0) * 1000)

        # Sanitize the joined model answer before persisting (#782, #1048).
        # Raw deltas were already forwarded untouched for progressive
        # rendering; the persisted form is the sanitized one.
        if joined_content:
            joined_content = sanitize_llm_output(joined_content)

        log = await llm_svc.create_query_log(
            db,
            endpoint_id=endpoint.id,
            user_id=claims["sub"],
            intent=intent,
            prompt=payload.prompt,
            system_prompt=system_prompt,
            response=joined_content or None,
            model_used=chosen_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_ms=duration_ms,
            error=error,
        )

        await audit(
            db,
            actor=claims["sub"],
            action="llm_query",
            resource_type="llm",
            resource_id=None,
            new_value={
                "query": payload.prompt[:200],
                "intent": intent,
                "model": chosen_model,
                "endpoint": endpoint.name,
                "stream": True,
            },
        )

        # Final `done` frame carries the persisted query_id so the UI can
        # reference it (rate-limit info, copy link, etc) without a separate
        # poll. SSE clients can stop reading after `[DONE]`.
        done_payload = {
            "type": "done",
            "query_id": str(log.id),
            "intent": intent,
            "model_used": chosen_model,
            "endpoint_name": endpoint.name,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "duration_ms": duration_ms,
        }
        if error:
            done_payload["error"] = error
        yield f"data: {json.dumps(done_payload)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            # Disable buffering at any reverse proxy in front of FastAPI so
            # the first token reaches the browser immediately.
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
