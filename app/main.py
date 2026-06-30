"""
app/main.py
===========
FastAPI application factory and entrypoint.

Wires together:
  - Lifespan (startup/shutdown: DB engine, Redis pool, Sentry)
  - Middleware (CORS, trusted hosts, request logging, Prometheus)
  - Exception handlers
  - The v1 API router
  - Health and readiness probes
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import AsyncGenerator

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import check_database_health, dispose_engine
from app.core.redis import check_redis_health, close_pool

logger = structlog.get_logger(__name__)


# =============================================================================
# Lifespan
# =============================================================================

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("app_starting", env=settings.APP_ENV, version=settings.APP_VERSION)

    # Sentry
    if settings.SENTRY_DSN:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration

        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=settings.SENTRY_ENVIRONMENT,
            traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
            profiles_sample_rate=settings.SENTRY_PROFILES_SAMPLE_RATE,
            integrations=[FastApiIntegration()],
        )
        logger.info("sentry_initialized")

    yield

    # Shutdown
    await dispose_engine()
    await close_pool()
    logger.info("app_shutdown_complete")


# =============================================================================
# App factory
# =============================================================================

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        docs_url=settings.docs_url,
        redoc_url=settings.redoc_url,
        openapi_url=settings.openapi_url,
        lifespan=lifespan,
    )

    # ── Middleware ────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if settings.is_production:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.TRUSTED_HOSTS)

    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
        )
        response.headers["X-Process-Time-Ms"] = str(duration_ms)
        return response

    # ── Prometheus metrics ────────────────────────────────────────────────────
    if settings.PROMETHEUS_ENABLED:
        from prometheus_fastapi_instrumentator import Instrumentator

        Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    # ── Exception handlers ────────────────────────────────────────────────────
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": exc.errors(), "error_code": "validation_error"},
        )

    @app.exception_handler(LookupError)
    async def lookup_exception_handler(request: Request, exc: LookupError):
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": str(exc), "error_code": "not_found"},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.error("unhandled_exception", path=request.url.path, error=str(exc), exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error", "error_code": "internal_error"},
        )

    # ── Routes ────────────────────────────────────────────────────────────────
    app.include_router(api_router, prefix=settings.api_prefix)

    @app.get("/health", tags=["health"], include_in_schema=False)
    async def health() -> dict:
        return {"status": "ok", "version": settings.APP_VERSION}

    @app.get("/health/ready", tags=["health"], include_in_schema=False)
    async def readiness() -> JSONResponse:
        db = await check_database_health()
        redis = await check_redis_health()
        healthy = db["status"] == "healthy" and redis["status"] == "healthy"
        return JSONResponse(
            status_code=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"database": db, "redis": redis, "ready": healthy},
        )

    return app


app = create_app()


def run() -> None:
    """Entry point for `sales-agent` console script."""
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.is_development,
        log_level=settings.APP_LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    run()
