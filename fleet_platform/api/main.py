from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.responses import Response

from fleet_platform.api.limiter import limiter
from fleet_platform.api.metrics_auth import verify_metrics_request
from fleet_platform.api.metrics_collectors import refresh_all_gauges
from fleet_platform.api.routes import (
    ansible,
    auth,
    baselines,
    drift,
    executions,
    fleet,
    fleet_health,
    groups,
    health,
    ingest,
    nodes,
    platform_settings,
    sbom,
    search,
)
from fleet_platform.api.routes.agent import router as agent_router
from fleet_platform.api.routes.alerts import router as alerts_router
from fleet_platform.api.routes.audit import router as audit_router
from fleet_platform.api.routes.builds import router as builds_router
from fleet_platform.api.routes.credentials import router as credentials_router
from fleet_platform.api.routes.group_secrets import router as group_secrets_router
from fleet_platform.api.routes.ios_tracking import router as ios_tracking_router
from fleet_platform.api.routes.llm import router as llm_router
from fleet_platform.api.routes.mobileconfig import router as mobileconfig_router
from fleet_platform.api.routes.monitoring import router as monitoring_router
from fleet_platform.api.routes.node_actions import actions_router
from fleet_platform.api.routes.node_actions import router as node_actions_router
from fleet_platform.api.routes.node_secrets import router as node_secrets_router
from fleet_platform.api.routes.oidc import router as oidc_router
from fleet_platform.api.routes.playbook_library import router as playbook_library_router
from fleet_platform.api.routes.provisioning import router as provisioning_router
from fleet_platform.api.routes.salt_keys import router as salt_keys_router
from fleet_platform.api.routes.salt_masters import router as salt_masters_router
from fleet_platform.api.routes.salt_ops import router as salt_ops_router
from fleet_platform.api.routes.security import router as security_router
from fleet_platform.api.routes.vnc import router as vnc_router
from fleet_platform.api.routes.webssh import router as webssh_router
from fleet_platform.core.config import VERSION, settings
from fleet_platform.core.errors import AppError, error_code_for_status
from fleet_platform.core.logging import configure_logging, get_logger
from fleet_platform.middleware.prometheus import PrometheusMiddleware
from fleet_platform.middleware.security_headers import SecurityHeaderMiddleware

_log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # configure_tracing() must run BEFORE configure_logging() so the trace_id
    # processor can read the real OTEL trace_id from the active span instead of
    # falling back to a random UUID4. The function is idempotent and a no-op
    # when OTEL_EXPORTER_OTLP_ENDPOINT is unset (dev / tests).
    from fleet_platform.core.tracing import (
        configure_tracing,
        instrument_httpx,
        instrument_redis,
        instrument_sqlalchemy,
    )

    configure_tracing(service_name="kri-api")
    configure_logging()
    instrument_sqlalchemy()
    instrument_httpx()
    instrument_redis()
    from fleet_platform.api.deps import close_redis, init_redis

    await init_redis()
    # Seed non-secret platform settings from env vars (fills gaps after DB wipe)
    from fleet_platform.db.session import AsyncSessionLocal
    from fleet_platform.services.platform_settings_svc import seed_settings_from_env
    from fleet_platform.services.user_seeding import seed_local_users

    async with AsyncSessionLocal() as db:
        await seed_settings_from_env(db)
        await seed_local_users(db)
    # Trigger a grain refresh immediately on every API container start so that
    # nodes do not stay offline after a kri deploy (salt minions reconnect but
    # do not re-push grains automatically; this queues a one-shot refresh).
    from fleet_platform.workers.ansible_tasks import refresh_all_node_grains

    refresh_all_node_grains.delay()
    # Ensure controller SSH keypair exists once at startup — not on every request.
    # Running here avoids blocking the settings GET endpoint with RSA keygen.
    from fleet_platform.services.ssh_keypair import ensure_controller_keypair

    try:
        ensure_controller_keypair()
    except PermissionError as exc:
        _log.warning("Could not create controller keypair at startup: %s", exc)
    yield
    await close_redis()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Fleet Platform API",
        version=VERSION,
        docs_url="/docs" if settings.is_development else None,
        redoc_url="/redoc" if settings.is_development else None,
        lifespan=lifespan,
    )

    # Instrument FastAPI here (not in lifespan) so HTTP middleware is wired
    # before the first request lands. configure_tracing() is called inside
    # lifespan, but FastAPIInstrumentor.instrument_app() is idempotent and
    # short-circuits when the SDK is not configured yet — first instrumented
    # request creates spans only if the lifespan setup succeeded.
    from fleet_platform.core.tracing import configure_tracing, instrument_fastapi

    configure_tracing(service_name="kri-api")
    instrument_fastapi(app)

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

    @app.exception_handler(HTTPException)
    async def structured_http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        code = exc.error_code if isinstance(exc, AppError) else error_code_for_status(exc.status_code)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error_code": code, "detail": exc.detail},
        )

    @app.exception_handler(RequestValidationError)
    async def structured_validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error_code": "UNPROCESSABLE", "detail": exc.errors()},
        )

    # Middleware execution order (Starlette applies in reverse-registration order;
    # last-added runs first / outermost):
    #   1. PrometheusMiddleware  — outermost, sees every request including CORS preflights
    #   2. CORSMiddleware        — handles preflight OPTIONS before auth/business logic
    #   3. SecurityHeaderMiddleware — innermost, adds security headers to all responses
    #
    # SecurityHeaderMiddleware is registered last so it runs innermost and adds headers
    # to the actual response after all routing; it must come after CORS so that CORS
    # headers set by CORSMiddleware are not overwritten.
    app.add_middleware(PrometheusMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Node-Token", "X-Jenkins-Secret"],
    )

    app.add_middleware(SecurityHeaderMiddleware)

    app.include_router(health.router, tags=["health"])
    app.include_router(auth.router, tags=["auth"])
    app.include_router(nodes.router, tags=["nodes"])
    app.include_router(ingest.router, tags=["ingest"])
    app.include_router(fleet.router, tags=["fleet"])
    app.include_router(groups.router, tags=["groups"])
    app.include_router(search.router, tags=["search"])
    app.include_router(baselines.router, tags=["baselines"])
    app.include_router(drift.router, tags=["drift"])
    app.include_router(executions.router, tags=["executions"])
    app.include_router(sbom.router, tags=["sbom"])
    app.include_router(ansible.router, tags=["ansible"])
    app.include_router(platform_settings.router, tags=["settings"])
    app.include_router(provisioning_router, tags=["provisioning"])
    app.include_router(security_router, tags=["security"])
    app.include_router(webssh_router, tags=["webssh"])
    app.include_router(vnc_router, tags=["vnc"])
    app.include_router(audit_router, tags=["audit"])
    app.include_router(salt_keys_router, tags=["salt"])
    app.include_router(salt_masters_router, tags=["salt-masters"])
    app.include_router(node_secrets_router, tags=["node-secrets"])
    app.include_router(group_secrets_router, tags=["group-secrets"])
    app.include_router(salt_ops_router, tags=["salt-ops"])
    app.include_router(alerts_router, tags=["alerts"])
    app.include_router(ios_tracking_router, tags=["ios"])
    app.include_router(mobileconfig_router, tags=["mobileconfig"])
    app.include_router(llm_router, tags=["llm"])
    app.include_router(fleet_health.router, tags=["fleet-health"])
    app.include_router(oidc_router, tags=["oidc"])
    app.include_router(builds_router, tags=["builds"])
    app.include_router(monitoring_router, tags=["monitoring"])
    app.include_router(node_actions_router)
    app.include_router(actions_router)
    app.include_router(credentials_router, tags=["credentials"])
    app.include_router(playbook_library_router, tags=["playbook-library"])
    app.include_router(agent_router, tags=["agent"])

    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint(request: Request):
        """Prometheus scrape endpoint — returns metrics in text/plain exposition format.

        Authentication (#763):
          Accepts one of:
            - Authorization: Bearer <METRICS_TOKEN>  (static scrape token; set via
              the METRICS_TOKEN env var and mirror it in the Prometheus scrape config:
                authorization: { credentials: <token> })
            - Authorization: Bearer <JWT>             (any valid kri access token)
          Returns 401 Unauthorized if neither is provided or both fail.

        Refreshes Redis-backed gauges (e.g. kri_node_ssh_reachable) and DB-backed
        gauges (node counts, beat heartbeat) before generating output so that each
        scrape reflects the latest state without any cross-process registry sharing
        (#356, #576).
        """
        verify_metrics_request(request, metrics_token=settings.metrics_token)
        refresh_all_gauges()
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        _log.error("unhandled_exception", path=str(request.url), exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"error_code": "INTERNAL_ERROR", "detail": "An unexpected error occurred"},
        )

    return app


app = create_app()
