from collections.abc import Awaitable, Callable
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncConnection
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.modules.governance.audit.application.ports.driven.audit_log import AuditLogPort
from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.modules.identity.application.ports.driven.token_verifier import AccessTokenClaims, AccessTokenVerifierPort
from app.platform.inbound.api.access_control.live_actor import LiveActor
from app.platform.inbound.api.audit_safety import record_audit_best_effort
from app.platform.inbound.api.path_matching import matches_any_prefix
from app.platform.inbound.api.system_tenant import SYSTEM_TENANT_ID
from app.shared_kernel.tenant_context import TenantContext

ResolveLiveActor = Callable[[str], Awaitable[LiveActor | None]]

_DENIED_BODY = {"error": "unauthorized"}


class RuntimeSessionPort(Protocol):
    """Request-scoped connection with SET LOCAL app.* GUCs. end() once per begin()."""

    async def begin(self, actor: LiveActor) -> AsyncConnection: ...

    async def end(self, conn: AsyncConnection, *, commit: bool) -> None: ...


class AccessControlMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        token_verifier: AccessTokenVerifierPort,
        resolve_live_actor: ResolveLiveActor,
        record_audit: AuditLogPort,
        runtime_session: RuntimeSessionPort,
        exempt_path_prefixes: frozenset[str] = frozenset(),
    ) -> None:
        super().__init__(app)
        self._token_verifier = token_verifier
        self._resolve_live_actor = resolve_live_actor
        self._record_audit = record_audit
        self._runtime_session = runtime_session
        self._exempt_path_prefixes = exempt_path_prefixes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if self._is_exempt(request.url.path):
            return await call_next(request)

        token = self._extract_bearer_token(request)
        if token is None:
            return self._deny(401)

        claims = self._token_verifier.verify(token)
        if claims is None:
            # Bad/expired token — no reliable tenant_id to audit against.
            return self._deny(401)

        # Missing claims (including anonymous/system tokens with no sub) → deny + audit.
        if not claims.sub or not claims.tenant_id or not claims.site_id or not claims.role:
            await self._audit_unmapped(claims, reason="access token is missing required claims")
            return self._deny(401)

        actor = await self._resolve_live_actor(claims.sub)
        if actor is None:
            await self._audit_unmapped(claims, reason="authenticated identity has no resolvable users row")
            return self._deny(401)

        if not actor.is_active:
            await self._audit_inactive(actor)
            return self._deny(403)

        return await self._forward_with_session(request, call_next, actor)

    async def _forward_with_session(
        self, request: Request, call_next: RequestResponseEndpoint, actor: LiveActor
    ) -> Response:
        ctx = TenantContext(tenant_id=actor.tenant_id, role=actor.role, site_id=actor.site_id, actor_id=actor.user_id)
        conn = await self._runtime_session.begin(actor)
        request.state.tenant_context = ctx
        request.state.live_actor = actor
        request.state.db_conn = conn

        commit = False
        try:
            response = await call_next(request)
            commit = response.status_code < 500
            return response
        finally:
            await self._runtime_session.end(conn, commit=commit)

    async def _audit_unmapped(self, claims: AccessTokenClaims, *, reason: str) -> None:
        # Missing tenant_id claim → SYSTEM_TENANT_ID so the deny is still audited.
        tenant_id = claims.tenant_id or SYSTEM_TENANT_ID
        # Best-effort: audit failure must not turn this deny into a 500.
        await record_audit_best_effort(
            self._record_audit,
            AuditEntry(
                tenant_id=tenant_id,
                actor_type=AuditActorType.SYSTEM,
                action=AuditAction.AUTH_UNMAPPED_IDENTITY,
                object_type="user",
                reason=reason,
                payload={"sub": claims.sub},
            ),
        )

    async def _audit_inactive(self, actor: LiveActor) -> None:
        # Best-effort: audit failure must not turn this deny into a 500.
        await record_audit_best_effort(
            self._record_audit,
            AuditEntry(
                tenant_id=actor.tenant_id,
                site_id=actor.site_id,
                actor_id=actor.user_id,
                actor_type=AuditActorType.USER,
                action=AuditAction.AUTH_INACTIVE_ACTOR,
                object_type="user",
                object_id=actor.user_id,
                reason="users.status or staff_members.status is not 'active'",
            ),
        )

    @staticmethod
    def _extract_bearer_token(request: Request) -> str | None:
        header = request.headers.get("authorization")
        if not header or not header.startswith("Bearer "):
            return None
        token = header.removeprefix("Bearer ").strip()
        return token or None

    @staticmethod
    def _deny(status_code: int) -> JSONResponse:
        return JSONResponse(_DENIED_BODY, status_code=status_code)

    def _is_exempt(self, path: str) -> bool:
        return matches_any_prefix(path, self._exempt_path_prefixes)
