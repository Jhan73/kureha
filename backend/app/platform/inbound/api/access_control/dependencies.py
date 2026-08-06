import httpx
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncConnection

from app.platform.inbound.api.access_control.live_actor import LiveActor
from app.shared_kernel.tenant_context import TenantContext


def get_tenant_context(request: Request) -> TenantContext:
    return request.state.tenant_context


def get_live_actor(request: Request) -> LiveActor:
    return request.state.live_actor


def get_db_conn(request: Request) -> AsyncConnection:
    """The SAME connection `AccessControlMiddleware` opened for this
    request via `runtime_session.begin()` -- already RLS-scoped (`app.*`
    GUCs set), already inside the transaction the middleware commits/rolls
    back once the response is ready. Route handlers build their use case's
    adapters against THIS connection, never open a new one."""
    return request.state.db_conn


def get_http_client(request: Request) -> httpx.AsyncClient:
    """The process-wide `httpx.AsyncClient` created in `app/main.py`'s
    lifespan and stored on `app.state` -- reused across requests (a fresh
    client per request would defeat connection pooling for the exact same
    reason `SupabaseAuthAdapter`/`GoogleCalendarAdapter`'s own tests inject
    one client per adapter instance, not one per call)."""
    return request.app.state.http_client
