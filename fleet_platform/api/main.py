from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from fleet_platform.core.config import settings, VERSION
from fleet_platform.core.logging import configure_logging, get_logger
from fleet_platform.api.limiter import limiter
from fleet_platform.api.routes import (
    health, auth, nodes, ingest, fleet, groups, search, baselines, drift, executions, sbom,
    ansible, platform_settings
)
from fleet_platform.api.routes.provisioning import router as provisioning_router

_log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    # Seed non-secret platform settings from env vars (fills gaps after DB wipe)
    from fleet_platform.db.session import AsyncSessionLocal
    from fleet_platform.services.platform_settings_svc import seed_settings_from_env
    async with AsyncSessionLocal() as db:
        await seed_settings_from_env(db)
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
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
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

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        _log.error("unhandled_exception", path=str(request.url), exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred"}},
        )

    return app


app = create_app()
