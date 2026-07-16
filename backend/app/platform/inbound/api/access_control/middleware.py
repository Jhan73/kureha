"""`AccessControlMiddleware` (design.md §4.2, tasks.md tasks 5.1/5.2): the
FastAPI/Starlette middleware that turns an access JWT into a live-verified
`TenantContext` and the `SET LOCAL app.*` GUCs every RLS policy depends on.

Implements the exact three-step flow design.md §4.2's "Origen del contexto"
paragraph spells out, run on EVERY request before any query executes:

1. Validate the access token (signature + expiry) via `AccessTokenVerifierPort`.
2. Resolve the token's `sub` to a live `users`/`staff_members` row (never
   trust the token's own `tenant_id`/`site_id`/`role` claims for
   authorization -- they are a hint only). A token with no mappable `users`
   row, or one whose live status gate fails, is DENIED and AUDITED, never
   silently defaulted to a role (spec `access-control` -> "Token without a
   mapped identity is rejected"; spec `session-management` -> "Live
   Enforcement of Active Status").
3. Only once an active actor is resolved: emit the `SET LOCAL app.*` GUCs
   (via the injected `runtime_session`) and hand the request downstream.

**Dependency shape, deliberately callables/protocols, not concrete
adapters:** `resolve_live_actor`/`record_audit` hide their own connection
lifecycle (both run against the elevated, pre-context `app.db.engine`, same
contract as `PostgresUserDirectory`/`Login._deny_unmapped` -- see those
docstrings) so this class stays unit-testable with fakes, mirroring every
other orchestration layer in this codebase (e.g. `Login`,
`RefreshToken`). `runtime_session` hides the `app.db.runtime_engine`
connection-open + `SET LOCAL` + commit/rollback lifecycle the SAME way.
Composition root (task 10.2, not yet built) is where these get wired to the
real Postgres engines.

**Status codes, deliberately distinguished (design decision, not spelled
out verbatim in design.md):** 401 when no session/identity could be
established at all (missing/invalid/malformed token, unmapped identity) --
"the caller was never authenticated as anyone real, retry with a fresh
token"; 403 when identity WAS established but the live active-status gate
denies it -- "we know who you are, access is forbidden". Both response
bodies are the SAME generic `{"error": "unauthorized"}` regardless of cause
(spec `access-control` -> "the caller receives a generic denial, not a
not-found vs forbidden distinction")."""

from typing import Awaitable, Callable, Protocol

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
    """Opens/closes the request-scoped `app.db.runtime_engine` connection
    with `SET LOCAL app.*` GUCs already projected (design.md §4.2). `begin`
    is only ever called for an active `LiveActor` (never for a denied
    request) -- `end` always runs exactly once per `begin`, in a `finally`,
    with `commit=False` on any 5xx response or unhandled exception."""

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
            # Bad signature, expired, malformed -- no reliable tenant_id to
            # audit against, and no spec scenario mandates one for this
            # branch (only "missing claims"/"unmapped identity" do).
            return self._deny(401)

        # This branch lumps together two distinct cases: a genuinely
        # malformed/incomplete token, AND a token shaped like PR 5's
        # documented anonymous/system `TenantContext` (`actor_id=None` ->
        # no `sub` claim at all, see `jwt_access_token_issuer.py`'s
        # `if ctx.actor_id is not None: claims["sub"] = ctx.actor_id`).
        # Anonymous/system tokens are also DENIED here -- not because a spec
        # says so, but because none of `design.md`, `specs/
        # patient-self-service-portal`, or `specs/embedded-patient-chat`
        # defines an anonymous-actor flow through THIS middleware yet.
        # If/when a future phase adds one (e.g. embedded patient chat,
        # where a visitor may need to act before/without a mapped
        # `users` row), this branch will need to stop conflating
        # "anonymous" with "malformed" and route anonymous tokens to their
        # own handling instead of unconditionally auditing+denying as
        # `AUTH_UNMAPPED_IDENTITY`.
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
        # CRITICAL fix #3 (kureha-mvp PR 6 verify-report, obs #414): a token
        # whose `tenant_id` claim is missing entirely -- only reachable via a
        # forged/malformed token, since Kureha's own issuer always includes
        # it -- has no real tenant to attach the (NOT NULL
        # `audit_logs.tenant_id`) audit row to. Falls back to the
        # well-known `SYSTEM_TENANT_ID` sentinel (see `system_tenant.py`)
        # instead of silently no-op'ing, so the access-control spec's
        # "Missing session claims... rejection MUST be recorded" is met
        # even in this edge case.
        tenant_id = claims.tenant_id or SYSTEM_TENANT_ID
        # Fresh-review CRITICAL fix #1: `record_audit_best_effort` swallows
        # any failure from the write itself (e.g. the FK violation
        # `SYSTEM_TENANT_ID` triggers against a real Postgres adapter) so
        # it can never turn this DENY into an unhandled 500.
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
        # Fresh-review CRITICAL fix #1: same guarantee as `_audit_unmapped`
        # above -- a failed audit write must never turn this DENY into an
        # unhandled 500.
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
