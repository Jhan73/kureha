"""`AuthRateLimitMiddleware` (design.md §19 layer 3, tasks.md task 5.3a):
throttles the auth mint/refresh endpoints by IP via the `rate_counters`
UPSERT (`FixedWindowRateLimiter` + `PostgresRateCounterStore`, wired by the
composition root -- task 10.2, not yet built). Only requests whose path
starts with one of `protected_path_prefixes` are checked; everything else
passes through untouched.

**IP dimension only, deliberately** -- the `auth_account` dimension (design.md
§4.4's `rate_counters.dimension` enum also lists it) needs the attempted
account/email, which only the login/refresh ROUTE HANDLER can read (it
requires parsing the request body, and Phase 10's routers do not exist yet).
`FixedWindowRateLimiter`/`PostgresRateCounterStore` are dimension-agnostic,
so a future Phase 10 handler can call them directly with `dimension=
"auth_account"` for that check; this middleware only covers the
IP-based `auth_ip` dimension, which is available pre-body-parse.

**Wiring `check_rate_limit`, deliberately NOT `FixedWindowRateLimiter.check`
directly (fresh-review pass CRITICAL fix #2):** `CheckRateLimit` is
`Callable[[str], Awaitable[bool]]`, called positionally as
`check_rate_limit(subject)`, but `FixedWindowRateLimiter.check`'s
parameters (`dimension`/`subject`/`window_seconds`/`limit`/`tenant_id`/`by`)
are all keyword-only with no single-positional-`str` form -- it cannot
satisfy `CheckRateLimit` as-is. `build_auth_ip_rate_limit_check` below is
the adapter: it closes over a fixed `dimension="auth_ip"`, `window_seconds`,
and `limit` and exposes exactly the shape this middleware requires. The
composition root (task 10.2, not yet built) is where this gets wired to a
real `FixedWindowRateLimiter` + `PostgresRateCounterStore`.

**Audit, closing the gap (kureha-mvp PR 6 verify-report CRITICAL #2, obs
#414):** the `platform-hardening` spec requires "the throttling event MUST
be auditable". `audit_logs.tenant_id` is `NOT NULL` and the pre-login IP
dimension genuinely has no tenant at the point of throttling (design.md
§4.4: "el limite pre-login por IP no tiene tenant aun"), so a denied
request is audited as `AuditAction.AUTH_RATE_LIMITED` under the
well-known `SYSTEM_TENANT_ID` sentinel (see `system_tenant.py` for why).
The `rate_counters` row remains the durable rate-limiting state; this
`audit_logs` row is the durable, spec-mandated record of the throttling
*event* itself. That audit write is best-effort (fresh-review CRITICAL fix
#1, see `audit_safety.py`) -- a failure there can never turn the intended
429 into an unhandled 500."""

from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.modules.governance.audit.application.ports.driven.audit_log import AuditLogPort
from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.platform.inbound.api.audit_safety import record_audit_best_effort
from app.platform.inbound.api.path_matching import matches_any_prefix
from app.platform.inbound.api.rate_limit.fixed_window_limiter import FixedWindowRateLimiter
from app.platform.inbound.api.system_tenant import SYSTEM_TENANT_ID

CheckRateLimit = Callable[[str], Awaitable[bool]]

_RATE_LIMITED_BODY = {"error": "rate_limited"}

_AUTH_IP_DIMENSION = "auth_ip"


def build_auth_ip_rate_limit_check(
    limiter: FixedWindowRateLimiter, *, window_seconds: int, limit: int
) -> CheckRateLimit:
    """Adapts `FixedWindowRateLimiter.check` (keyword-only, dimension-
    agnostic) into the single-positional-`str`-arg `CheckRateLimit` shape
    `AuthRateLimitMiddleware` requires, closing over the fixed `auth_ip`
    dimension plus this call's `window_seconds`/`limit` (fresh-review
    CRITICAL fix #2). No `tenant_id` -- the pre-login IP dimension has none
    yet (design.md §4.4)."""

    async def check_rate_limit(subject: str) -> bool:
        return await limiter.check(
            dimension=_AUTH_IP_DIMENSION,
            subject=subject,
            window_seconds=window_seconds,
            limit=limit,
        )

    return check_rate_limit


class AuthRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        check_rate_limit: CheckRateLimit,
        protected_path_prefixes: frozenset[str],
        record_audit: AuditLogPort,
        trust_forwarded_for: bool = False,
    ) -> None:
        """`trust_forwarded_for` (default `False`, preserving prior
        behavior exactly): only set to `True` when the deployment topology
        GUARANTEES `X-Forwarded-For` is set/overwritten by a trusted reverse
        proxy in front of this service -- never trust it directly from an
        untrusted client, which could otherwise spoof its throttling
        subject at will. Not wired to a real value yet: the composition
        root (task 10.2) and the AWS deployment topology it would depend on
        don't exist yet."""
        super().__init__(app)
        self._check_rate_limit = check_rate_limit
        self._protected_path_prefixes = protected_path_prefixes
        self._record_audit = record_audit
        self._trust_forwarded_for = trust_forwarded_for

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self._is_protected(request.url.path):
            return await call_next(request)

        subject = self._resolve_subject(request)
        allowed = await self._check_rate_limit(subject)
        if not allowed:
            await self._audit_rate_limited(subject, request.url.path)
            return JSONResponse(_RATE_LIMITED_BODY, status_code=429)

        return await call_next(request)

    async def _audit_rate_limited(self, subject: str, path: str) -> None:
        # Fresh-review CRITICAL fix #1: `record_audit_best_effort` swallows
        # any failure from the write itself (e.g. the FK violation
        # `SYSTEM_TENANT_ID` triggers against a real Postgres adapter) so
        # it can never turn this 429 into an unhandled 500.
        await record_audit_best_effort(
            self._record_audit,
            AuditEntry(
                tenant_id=SYSTEM_TENANT_ID,
                actor_type=AuditActorType.SYSTEM,
                action=AuditAction.AUTH_RATE_LIMITED,
                object_type="auth_rate_limit",
                reason="rate limit exceeded for pre-login auth endpoint",
                payload={"subject": subject, "path": path},
            ),
        )

    def _resolve_subject(self, request: Request) -> str:
        if self._trust_forwarded_for:
            forwarded_for = request.headers.get("x-forwarded-for")
            if forwarded_for:
                return forwarded_for.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _is_protected(self, path: str) -> bool:
        return matches_any_prefix(path, self._protected_path_prefixes)
