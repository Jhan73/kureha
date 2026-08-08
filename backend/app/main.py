from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.composition_root import (
    bootstrap_rbac_catalog_and_grants,
    build_access_token_verifier,
    build_operator_credential_verifier,
    build_runtime_session,
    open_elevated_connection,
    open_runtime_connection,
)
from app.config import settings
from app.modules.governance.audit.adapters.outbound.postgres.audit_log import PostgresAuditLog
from app.modules.governance.audit.domain.audit_entry import AuditEntry
from app.platform.inbound.api.access_control.adapters.postgres_live_actor_resolver import PostgresLiveActorResolver
from app.platform.inbound.api.access_control.live_actor import LiveActor
from app.platform.inbound.api.access_control.middleware import AccessControlMiddleware
from app.platform.inbound.api.errors import register_exception_handlers
from app.platform.inbound.api.rate_limit.adapters.postgres_rate_counter_store import PostgresRateCounterStore
from app.platform.inbound.api.rate_limit.auth_rate_limit_middleware import (
    AuthRateLimitMiddleware,
    build_auth_ip_rate_limit_check,
)
from app.platform.inbound.api.rate_limit.fixed_window_limiter import FixedWindowRateLimiter
from app.platform.inbound.api.routers import auth as auth_router
from app.platform.inbound.api.routers import calendar_oauth as calendar_oauth_router
from app.platform.inbound.api.routers import chat as chat_router
from app.platform.inbound.api.routers import ops_tenants as ops_tenants_router
from app.platform.inbound.api.routers import scheduling as scheduling_router
from app.platform.inbound.api.routers import staff as staff_router
from app.shared_kernel.clock import SystemClock

_ACCESS_CONTROL_EXEMPT_PATH_PREFIXES = frozenset(
    {"/auth/login", "/auth/refresh", "/auth/password-reset", "/ops", "/docs", "/openapi.json", "/redoc"}
)
_AUTH_RATE_LIMIT_PROTECTED_PREFIXES = frozenset({"/auth/login", "/auth/refresh", "/auth/password-reset"})
_AUTH_RATE_LIMIT_WINDOW_SECONDS = 60
_AUTH_RATE_LIMIT_MAX_ATTEMPTS = 10


class _ElevatedAuditLog:
    async def record(self, entry: AuditEntry) -> str:
        async with open_elevated_connection() as conn:
            return await PostgresAuditLog(conn).record(entry)


class _ElevatedRateCounterStore:
    async def increment(self, *, dimension, subject, window_start, by=1, tenant_id=None) -> int:
        async with open_elevated_connection() as conn:
            return await PostgresRateCounterStore(conn).increment(
                dimension=dimension, subject=subject, window_start=window_start, by=by, tenant_id=tenant_id
            )

    async def peek(self, *, dimension, subject, window_start, tenant_id=None) -> int:
        async with open_elevated_connection() as conn:
            return await PostgresRateCounterStore(conn).peek(
                dimension=dimension, subject=subject, window_start=window_start, tenant_id=tenant_id
            )


async def _resolve_live_actor(user_id: str) -> LiveActor | None:
    async with open_elevated_connection() as conn:
        return await PostgresLiveActorResolver(conn).resolve(user_id)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    app.state.http_client = httpx.AsyncClient(timeout=10.0)
    async with open_runtime_connection() as conn:
        await bootstrap_rbac_catalog_and_grants(conn)
    try:
        yield
    finally:
        await app.state.http_client.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="Kureha API", lifespan=_lifespan)

    register_exception_handlers(app)

    app.include_router(auth_router.router)
    app.include_router(scheduling_router.router)
    app.include_router(calendar_oauth_router.router)
    app.include_router(chat_router.router)
    app.include_router(staff_router.router)
    if settings.ops_bootstrap_enabled:
        app.include_router(ops_tenants_router.router)

    app.state.operator_credential_verifier = build_operator_credential_verifier()

    audit_log = _ElevatedAuditLog()

    app.add_middleware(
        AccessControlMiddleware,
        token_verifier=build_access_token_verifier(),
        resolve_live_actor=_resolve_live_actor,
        record_audit=audit_log,
        runtime_session=build_runtime_session(),
        exempt_path_prefixes=_ACCESS_CONTROL_EXEMPT_PATH_PREFIXES,
    )

    limiter = FixedWindowRateLimiter(_ElevatedRateCounterStore(), clock=SystemClock())
    app.add_middleware(
        AuthRateLimitMiddleware,
        check_rate_limit=build_auth_ip_rate_limit_check(
            limiter, window_seconds=_AUTH_RATE_LIMIT_WINDOW_SECONDS, limit=_AUTH_RATE_LIMIT_MAX_ATTEMPTS
        ),
        protected_path_prefixes=_AUTH_RATE_LIMIT_PROTECTED_PREFIXES,
        record_audit=audit_log,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in settings.cors_allowed_origins.split(",") if origin.strip()],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return app


app = create_app()
