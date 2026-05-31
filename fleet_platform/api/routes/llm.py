import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.audit import audit
from fleet_platform.core.auth import require_role
from fleet_platform.schemas.llm import (
    LLMEndpointCreate,
    LLMEndpointResponse,
    LLMEndpointTestResponse,
    LLMEndpointUpdate,
    LLMQueryLogEntry,
    LLMQueryRequest,
    LLMQueryResponse,
)
from fleet_platform.services import llm_svc
from fleet_platform.services.llm_caller import LLMCallError, call_anthropic, call_openai_compat
from fleet_platform.services.llm_context import build_fleet_context
from fleet_platform.services.model_catalog import get_models
from fleet_platform.services.model_discovery import discover_models

router = APIRouter(prefix="/api/v1/llm", tags=["llm"])


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
    """Query a provider endpoint and return available model IDs."""
    models = await discover_models(req.url, req.provider)
    return {"models": models}


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
    _: dict = Depends(require_role("admin")),
):
    endpoint = await llm_svc.create_endpoint(db, payload)
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
    _: dict = Depends(require_role("admin")),
):
    endpoint = await llm_svc.get_endpoint(db, endpoint_id)
    if not endpoint:
        raise HTTPException(status_code=404, detail="LLM endpoint not found")
    endpoint = await llm_svc.update_endpoint(db, endpoint, payload)
    return _to_response(endpoint)


@router.delete("/endpoints/{endpoint_id}", status_code=204)
async def delete_endpoint(
    endpoint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    endpoint = await llm_svc.get_endpoint(db, endpoint_id)
    if not endpoint:
        raise HTTPException(status_code=404, detail="LLM endpoint not found")
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
    t0 = time.perf_counter()
    try:
        if endpoint.provider == "anthropic":
            await call_anthropic(
                api_key=api_key or "",
                model=endpoint.model,
                max_tokens=16,
                system_prompt="You are a test probe.",
                user_prompt=ping_prompt,
            )
        else:
            await call_openai_compat(
                base_url=endpoint.base_url,
                api_key=api_key,
                model=endpoint.model,
                max_tokens=16,
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
async def submit_query(
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
    system_prompt = await build_fleet_context(db, payload.intent)

    history_dicts: list[dict] = [
        {"role": m.role, "content": m.content}
        for m in payload.history
    ] if payload.history else []

    # Enforce a 6000-token total history budget — drop oldest turns first.
    # Rough estimate: 1 token ≈ 4 chars.
    _HISTORY_TOKEN_BUDGET = 6000
    total_chars = sum(len(m["content"]) for m in history_dicts)
    while history_dicts and total_chars > _HISTORY_TOKEN_BUDGET * 4:
        removed = history_dicts.pop(0)
        total_chars -= len(removed["content"])

    t0 = time.perf_counter()
    error: str | None = None
    content: str = ""
    input_tokens = 0
    output_tokens = 0

    try:
        if endpoint.provider == "anthropic":
            content, input_tokens, output_tokens = await call_anthropic(
                api_key=api_key or "",
                model=endpoint.model,
                max_tokens=endpoint.max_tokens,
                system_prompt=system_prompt,
                user_prompt=payload.prompt,
                history=history_dicts,
            )
        else:
            content, input_tokens, output_tokens = await call_openai_compat(
                base_url=endpoint.base_url,
                api_key=api_key,
                model=endpoint.model,
                max_tokens=endpoint.max_tokens,
                system_prompt=system_prompt,
                user_prompt=payload.prompt,
                history=history_dicts,
            )
    except (LLMCallError, Exception) as exc:
        error = str(exc)

    duration_ms = int((time.perf_counter() - t0) * 1000)

    log = await llm_svc.create_query_log(
        db,
        endpoint_id=endpoint.id,
        user_id=claims["sub"],
        intent=payload.intent,
        prompt=payload.prompt,
        system_prompt=system_prompt,
        response=content or None,
        model_used=endpoint.model,
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
            "intent": payload.intent,
            "model": endpoint.model,
            "endpoint": endpoint.name,
        },
    )

    if error:
        raise HTTPException(status_code=502, detail=f"LLM call failed: {error}")

    return LLMQueryResponse(
        query_id=log.id,
        intent=payload.intent,
        result=content,
        model_used=endpoint.model,
        endpoint_name=endpoint.name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        duration_ms=duration_ms,
    )


@router.get("/queries", response_model=list[LLMQueryLogEntry])
async def list_queries(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    logs = await llm_svc.list_query_logs(db, user_id=claims["sub"], limit=50)
    return [LLMQueryLogEntry.model_validate(log) for log in logs]
