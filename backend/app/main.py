"""FastAPI application factory (design.md §2.5's `platform/inbound/api/`,
tasks.md tasks 10.1/10.2/10.3): the process entry point `uvicorn app.main:app`
serves. Ties together everything PR5/PR6/this session's composition_root
additions built but nothing had assembled into a running app yet:

1. **Task 10.3** -- calls `register_exception_handlers(app)`
   (`platform/inbound/api/errors.py`, already complete since a prior
   session, just never wired into an app until now).
2. **Task 10.2's forward pointer** -- the lifespan hook calls
   `bootstrap_rbac_catalog_and_grants()` exactly once, against
   `open_runtime_connection()`, before the app starts serving traffic
   (`composition_root.py`'s own docstring: "The future app factory's
   lifespan MUST call this once... before serving traffic").
3. **Task 5.1/5.2/5.3 (PR6)** -- mounts `AccessControlMiddleware` and
   `AuthRateLimitMiddleware`, both built in PR6 as pure orchestration
   classes taking Protocol dependencies (`resolve_live_actor`,
   `record_audit`, `runtime_session`, `check_rate_limit`) with an explicit
   note that "Composition root (task 10.2, not yet built) is where these
   get wired to the real Postgres engines" -- this module is that wiring,
   for the first time.
4. **Task 10.1** -- mounts the auth/scheduling/calendar-oauth routers.
5. **Task 11.7 (PR 11 batch 3)** -- mounts the chat router (`POST /chat`),
   the non-streaming LangGraph invocation endpoint -- see
   `routers/chat.py`'s own module docstring for its `thread_id`
   ownership-validation contract (design.md §8.6).

**`_ElevatedAuditLog`/`_ElevatedRateCounterStore`/`_resolve_live_actor`
below are NOT in `composition_root.py`** -- they are glue that is specific
to wiring THESE TWO MIDDLEWARES' single, constructor-injected dependencies
(built once at app startup, not per-request), not reusable use-case wiring
the way every `build_*` function in `composition_root.py` is. Both need a
FRESH `open_elevated_connection()` per call (there is no per-request
connection yet at the point either middleware runs -- see
`PostgresLiveActorResolver`/`PostgresRateCounterStore`'s own docstrings),
which is why they cannot just be `PostgresAuditLog(conn)`/
`PostgresRateCounterStore(conn)` constructed once."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.composition_root import (
    bootstrap_rbac_catalog_and_grants,
    build_access_token_verifier,
    build_runtime_session,
    open_elevated_connection,
    open_runtime_connection,
)
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
from app.platform.inbound.api.routers import scheduling as scheduling_router
from app.shared_kernel.clock import SystemClock

# `/auth/login`/`/auth/refresh` are pre-auth by definition -- see
# `routers/auth.py`'s module docstring. `/docs`/`/openapi.json`/`/redoc` are
# FastAPI's own tooling routes, never behind a caller's session.
_ACCESS_CONTROL_EXEMPT_PATH_PREFIXES = frozenset({"/auth/login", "/auth/refresh", "/docs", "/openapi.json", "/redoc"})

# design.md §19 layer 3 / tasks.md task 5.3a: only the auth mint/refresh
# routes are throttled by IP pre-login.
_AUTH_RATE_LIMIT_PROTECTED_PREFIXES = frozenset({"/auth/login", "/auth/refresh"})
_AUTH_RATE_LIMIT_WINDOW_SECONDS = 60
_AUTH_RATE_LIMIT_MAX_ATTEMPTS = 10


class _ElevatedAuditLog:
    """`AuditLogPort` impl opening its own `open_elevated_connection()` per
    `record()` call. See this module's own docstring for why this cannot be
    a plain `PostgresAuditLog(conn)` built once at startup."""

    async def record(self, entry: AuditEntry) -> str:
        async with open_elevated_connection() as conn:
            return await PostgresAuditLog(conn).record(entry)


class _ElevatedRateCounterStore:
    """`RateCounterStorePort` impl, same "fresh elevated connection per
    call" shape as `_ElevatedAuditLog` above -- `PostgresRateCounterStore`'s
    own docstring: "wired against `app.db.engine` (elevated)... since the
    auth-throttle dimension runs pre-context (no `app.*` GUC exists yet)"."""

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
    """`AccessControlMiddleware`'s `resolve_live_actor` dependency -- fresh
    elevated connection per call, same reasoning as `_ElevatedAuditLog`
    above (`PostgresLiveActorResolver`'s own docstring: "the composition
    root MUST construct this against `app.db.engine`, never
    `app.db.runtime_engine`")."""
    async with open_elevated_connection() as conn:
        return await PostgresLiveActorResolver(conn).resolve(user_id)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
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

    audit_log = _ElevatedAuditLog()

    # Added FIRST via `add_middleware` -> ends up INNERMOST among user
    # middlewares (Starlette prepends on each call) -> runs SECOND per
    # request, right after the rate limiter. Harmless either way today
    # (the two middlewares' path sets never overlap -- `/auth/login`/
    # `/auth/refresh` are exempt from `AccessControlMiddleware`), but
    # "throttle before resolving identity" is the more defensible default
    # order for any future overlapping route.
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

    return app


app = create_app()
