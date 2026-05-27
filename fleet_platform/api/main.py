from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.responses import Response

from fleet_platform.api.limiter import limiter
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
from fleet_platform.api.routes.alerts import router as alerts_router
from fleet_platform.api.routes.audit import router as audit_router
from fleet_platform.api.routes.oidc import router as oidc_router
from fleet_platform.api.routes.group_secrets import router as group_secrets_router
from fleet_platform.api.routes.ios_tracking import router as ios_tracking_router
from fleet_platform.api.routes.llm import router as llm_router
from fleet_platform.api.routes.node_secrets import router as node_secrets_router
from fleet_platform.api.routes.provisioning import router as provisioning_router
from fleet_platform.api.routes.salt_keys import router as salt_keys_router
from fleet_platform.api.routes.salt_ops import router as salt_ops_router
from fleet_platform.api.routes.security import router as security_router
from fleet_platform.api.routes.vnc import router as vnc_router
from fleet_platform.api.routes.webssh import router as webssh_router
from fleet_platform.core.config import VERSION, settings
from fleet_platform.core.logging import configure_logging, get_logger
from fleet_platform.middleware.prometheus import PrometheusMiddleware

_log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    # Seed non-secret platform settings from env vars (fills gaps after DB wipe)
    from fleet_platform.db.session import AsyncSessionLocal
    from fleet_platform.services.platform_settings_svc import seed_settings_from_env
    from fleet_platform.services.user_seeding import seed_local_users
    async with AsyncSessionLocal() as db:
        await seed_settings_from_env(db)
        await seed_local_users(db)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Fleet Platform API",
        version=VERSION,
        docs_url="/docs" if settings.is_development else None,
        redoc_url="/redoc" if settings.is_development else None,
        lifespan=lifespan,
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

    # Prometheus middleware must be added before CORS so it sees every request.
    # Starlette applies middleware in reverse-registration order (last-added runs first),
    # so PrometheusMiddleware is registered first and therefore executes outermost.
    app.add_middleware(PrometheusMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Node-Token"],
    )

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
    app.include_router(node_secrets_router, tags=["node-secrets"])
    app.include_router(group_secrets_router, tags=["group-secrets"])
    app.include_router(salt_ops_router, tags=["salt-ops"])
    app.include_router(alerts_router, tags=["alerts"])
    app.include_router(ios_tracking_router, tags=["ios"])
    app.include_router(llm_router, tags=["llm"])
    app.include_router(fleet_health.router, tags=["fleet-health"])
    app.include_router(oidc_router, tags=["oidc"])

    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint():
        """Prometheus scrape endpoint — returns metrics in text/plain exposition format."""
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        _log.error("unhandled_exception", path=str(request.url), exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred"}},
        )

    return app


app = create_app()
