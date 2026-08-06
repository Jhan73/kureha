from collections.abc import Awaitable, Callable

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
    """Adapts FixedWindowRateLimiter into CheckRateLimit for auth_ip (no tenant yet)."""

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
        """`trust_forwarded_for=True` only behind a proxy that overwrites X-Forwarded-For."""
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
        # Best-effort: audit failure must not turn this 429 into a 500.
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
