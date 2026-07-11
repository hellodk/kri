# fleet_platform/services/fleet_recommendations_svc.py
"""Fleet-wide, LLM-generated recommendations (#4).

Replaces the per-node "Ask AI" quick-fix (#294) with a single, stored,
prioritized recommendation feed for the whole fleet — generated daily by
Celery beat and on-demand by an operator.
"""

import logging

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.models.fleet_recommendation import FleetRecommendation
from fleet_platform.models.node import Node
from fleet_platform.services.llm_caller import call_anthropic, call_openai_compat
from fleet_platform.services.llm_context import build_fleet_context
from fleet_platform.services.llm_svc import get_decrypted_api_key, get_default_endpoint

logger = logging.getLogger(__name__)

_MAX_TOKENS = 1500

_SYSTEM_PROMPT = (
    "You are an experienced Site Reliability Engineer reviewing the entire node fleet below. "
    "Produce a prioritized, actionable list of recommendations for the fleet operator.\n\n"
    "Group your recommendations under these theme headings, in this order, and OMIT any "
    "heading that has no findings:\n"
    "## Reliability\n"
    "## Security / CVEs\n"
    "## Drift\n"
    "## Capacity\n\n"
    "For each recommendation:\n"
    "- State a severity: **Critical**, **High**, **Medium**, or **Low**.\n"
    "- Name the specific affected node(s) by hostname (never invent a node not shown below).\n"
    "- Give one concrete, actionable next step.\n\n"
    "Be concise. Use Markdown. Do not speculate about data that is not present in the context below — "
    "if a theme has nothing notable, omit it entirely rather than inventing filler."
)


async def _resolve_model(endpoint) -> str:
    """Resolve the endpoint's '__auto__' sentinel to a concrete healthy model id.

    Mirrors api/routes/llm.py::_resolve_model but raises ValueError (not
    HTTPException) so it composes with this service's error handling. Non-auto
    endpoints return their model unchanged.
    """
    if endpoint.model != "__auto__":
        return endpoint.model

    from fleet_platform.services import model_health_cache as hc
    from fleet_platform.services.model_discovery import discover_models_with_health

    url = endpoint.base_url or ""
    provider = endpoint.provider
    if hc.is_stale(url, provider):
        await discover_models_with_health(url, provider, api_key=get_decrypted_api_key(endpoint))
    healthy = hc.get_healthy_models(url, provider)
    if not healthy:
        raise ValueError(
            f"No healthy model available on endpoint '{endpoint.name}' for auto-selection."
        )
    return healthy[0]["id"]


async def generate_fleet_recommendations(db: AsyncSession, generated_by: str) -> FleetRecommendation:
    """Generate a fresh fleet-wide recommendation set and persist it.

    Raises ValueError if no LLM endpoint is configured/enabled, or LLMCallError
    if the provider call fails.
    """
    endpoint = await get_default_endpoint(db)
    if not endpoint or not endpoint.enabled:
        raise ValueError("No LLM endpoint configured.")
    resolved_model = await _resolve_model(endpoint)

    # build_fleet_context returns (system_prompt, rag_citations) — the second
    # element is RAG citations, not node records (RAG is only performed for
    # fleet_query/fleet_command intents, so it is always empty here). Node
    # count for the persisted row is fetched separately.
    _fleet_context, _citations = await build_fleet_context(db, "recommendations")
    node_count_result = await db.execute(select(func.count()).select_from(Node))
    node_count: int = node_count_result.scalar_one()
    api_key = get_decrypted_api_key(endpoint)

    if endpoint.provider == "anthropic":
        content, _input_tokens, _output_tokens = await call_anthropic(
            api_key=api_key or "",
            model=resolved_model,
            max_tokens=_MAX_TOKENS,
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=_fleet_context,
        )
    else:
        model_caps = (
            [c.strip() for c in endpoint.model_capabilities.split(",") if c.strip()]
            if endpoint.model_capabilities
            else []
        )
        content, _input_tokens, _output_tokens = await call_openai_compat(
            base_url=endpoint.base_url,
            api_key=api_key,
            model=resolved_model,
            max_tokens=_MAX_TOKENS,
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=_fleet_context,
            model_context_length=endpoint.model_context_length,
            model_capabilities=model_caps,
        )

    recommendation = FleetRecommendation(
        content=content,
        model=resolved_model,
        node_count=node_count,
        provider=endpoint.provider,
        generated_by=generated_by,
    )
    db.add(recommendation)
    await db.commit()
    await db.refresh(recommendation)
    logger.info(
        "generate_fleet_recommendations: persisted recommendation %s (generated_by=%s, node_count=%d)",
        recommendation.id,
        generated_by,
        recommendation.node_count,
    )
    return recommendation


async def get_latest_recommendation(db: AsyncSession) -> FleetRecommendation | None:
    """Return the newest stored recommendation, or None if none exist yet."""
    result = await db.execute(
        select(FleetRecommendation).order_by(desc(FleetRecommendation.generated_at)).limit(1)
    )
    return result.scalar_one_or_none()
