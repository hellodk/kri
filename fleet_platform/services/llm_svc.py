import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.models.llm_endpoint import LLMEndpoint
from fleet_platform.models.llm_query_log import LLMQueryLog
from fleet_platform.schemas.llm import LLMEndpointCreate, LLMEndpointUpdate
from fleet_platform.services.platform_settings_svc import decrypt_secret, encrypt_secret


async def list_endpoints(db: AsyncSession) -> list[LLMEndpoint]:
    result = await db.execute(select(LLMEndpoint).order_by(LLMEndpoint.created_at))
    return list(result.scalars().all())


async def get_endpoint(db: AsyncSession, endpoint_id: uuid.UUID) -> LLMEndpoint | None:
    result = await db.execute(
        select(LLMEndpoint).where(LLMEndpoint.id == endpoint_id)
    )
    return result.scalar_one_or_none()


async def get_default_endpoint(db: AsyncSession) -> LLMEndpoint | None:
    result = await db.execute(
        select(LLMEndpoint).where(
            LLMEndpoint.is_default == True,  # noqa: E712
            LLMEndpoint.enabled == True,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def create_endpoint(db: AsyncSession, payload: LLMEndpointCreate) -> LLMEndpoint:
    if payload.is_default:
        await db.execute(update(LLMEndpoint).values(is_default=False))
    endpoint = LLMEndpoint(
        name=payload.name,
        provider=payload.provider,
        base_url=payload.base_url,
        api_key_encrypted=encrypt_secret(payload.api_key) if payload.api_key else None,
        model=payload.model,
        max_tokens=payload.max_tokens,
        is_default=payload.is_default,
        enabled=payload.enabled,
    )
    db.add(endpoint)
    await db.commit()
    await db.refresh(endpoint)
    return endpoint


async def update_endpoint(
    db: AsyncSession, endpoint: LLMEndpoint, payload: LLMEndpointUpdate
) -> LLMEndpoint:
    if payload.name is not None:
        endpoint.name = payload.name
    if payload.base_url is not None:
        endpoint.base_url = payload.base_url
    if payload.api_key is not None:
        endpoint.api_key_encrypted = encrypt_secret(payload.api_key)
    if payload.model is not None:
        endpoint.model = payload.model
    if payload.max_tokens is not None:
        endpoint.max_tokens = payload.max_tokens
    if payload.enabled is not None:
        endpoint.enabled = payload.enabled
    if payload.is_default is not None:
        if payload.is_default:
            await db.execute(update(LLMEndpoint).values(is_default=False))
        endpoint.is_default = payload.is_default
    await db.commit()
    await db.refresh(endpoint)
    return endpoint


async def delete_endpoint(db: AsyncSession, endpoint: LLMEndpoint) -> None:
    await db.delete(endpoint)
    await db.commit()


def get_decrypted_api_key(endpoint: LLMEndpoint) -> str | None:
    if endpoint.api_key_encrypted is None:
        return None
    return decrypt_secret(endpoint.api_key_encrypted)


_SYSTEM_PROMPT_LOG_LIMIT = 500
_PROMPT_LOG_LIMIT = 2000


async def create_query_log(
    db: AsyncSession,
    *,
    endpoint_id: uuid.UUID | None,
    user_id: str,
    intent: str,
    prompt: str,
    system_prompt: str,
    response: str | None,
    model_used: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    duration_ms: int | None,
    error: str | None,
) -> LLMQueryLog:
    truncated_system_prompt = (
        system_prompt[:_SYSTEM_PROMPT_LOG_LIMIT] + "... [truncated]"
        if len(system_prompt) > _SYSTEM_PROMPT_LOG_LIMIT
        else system_prompt
    )
    truncated_user_prompt = (
        prompt[:_PROMPT_LOG_LIMIT] + "... [truncated]"
        if len(prompt) > _PROMPT_LOG_LIMIT
        else prompt
    )
    log = LLMQueryLog(
        endpoint_id=endpoint_id,
        user_id=user_id,
        intent=intent,
        prompt=truncated_user_prompt,
        system_prompt=truncated_system_prompt,
        response=response,
        model_used=model_used,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        duration_ms=duration_ms,
        error=error,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return log


async def list_query_logs(
    db: AsyncSession, user_id: str | None = None, limit: int = 50
) -> list[LLMQueryLog]:
    q = select(LLMQueryLog).order_by(LLMQueryLog.created_at.desc()).limit(limit)
    if user_id is not None:
        q = q.where(LLMQueryLog.user_id == user_id)
    result = await db.execute(q)
    return list(result.scalars().all())
