"""Task 5.3a: `AuthRateLimitMiddleware` -- layer 3 of design.md §19's rate
limiting: "Auth/token (baja frecuencia): sliding/fixed-window sobre
`rate_counters`... Exceso -> denegacion temporal auditada". Orchestration
only, tested against a fake rate-check callable (same fakes-only style as
`test_middleware.py`) -- the real UPSERT/window math is proven by
`test_postgres_rate_counter_store.py`/`test_fixed_window_limiter.py`.

Keyed by IP only (design.md §4.4: the pre-login auth-throttle dimension has
no `tenant_id` yet) -- only paths under `protected_path_prefixes` are
throttled, everything else passes through untouched.

CRITICAL fix #2 (kureha-mvp PR 6 verify report, obs #414): the
`platform-hardening` spec's "Rate Limiting on Authentication Endpoints"
requirement is explicit that "the throttling event MUST be auditable" --
`test_protected_path_over_the_limit_is_audited` and
`test_protected_path_under_the_limit_is_not_audited` close that gap."""

from starlette.requests import Request
from starlette.responses import Response

from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.platform.inbound.api.rate_limit.auth_rate_limit_middleware import AuthRateLimitMiddleware
from app.platform.inbound.api.system_tenant import SYSTEM_TENANT_ID


def _request(*, path: str = "/auth/login", client_host: str | None = "203.0.113.9") -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "raw_path": path.encode(),
        "headers": [],
        "query_string": b"",
        "client": (client_host, 12345) if client_host else None,
        "app": None,
    }
    return Request(scope)


async def _dummy_app(scope, receive, send) -> None:  # pragma: no cover
    raise NotImplementedError


def _request_with_headers(*, path: str = "/auth/login", client_host: str | None = "203.0.113.9", headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "raw_path": path.encode(),
        "headers": headers or [],
        "query_string": b"",
        "client": (client_host, 12345) if client_host else None,
        "app": None,
    }
    return Request(scope)


class _FakeAuditLog:
    """Mirrors `tests/platform/inbound/api/access_control/test_middleware.py::_FakeAuditLog`
    -- the `AuditLogPort` fake pattern already established there, reused here."""

    def __init__(self) -> None:
        self.recorded: list[AuditEntry] = []

    async def record(self, entry: AuditEntry) -> str:
        self.recorded.append(entry)
        return "audit-1"


class _FailingAuditLog:
    """CRITICAL fix #1 (fresh-review pass, kureha-mvp PR 6): an
    `AuditLogPort` fake whose `record()` always raises, used to prove a
    failed audit write can never replace the intended 429 with an
    unhandled 500 (e.g. an FK violation from `SYSTEM_TENANT_ID` having no
    seeded `tenants` row yet)."""

    async def record(self, entry: AuditEntry) -> str:
        raise RuntimeError("audit backend unavailable")


def _build_middleware(
    *,
    allowed: bool,
    protected_path_prefixes=frozenset({"/auth/login", "/auth/refresh"}),
    trust_forwarded_for: bool = False,
    audit_log: object | None = None,
):
    calls: list[str] = []
    audit_log = audit_log if audit_log is not None else _FakeAuditLog()

    async def check_rate_limit(subject: str) -> bool:
        calls.append(subject)
        return allowed

    middleware = AuthRateLimitMiddleware(
        _dummy_app,
        check_rate_limit=check_rate_limit,
        protected_path_prefixes=protected_path_prefixes,
        trust_forwarded_for=trust_forwarded_for,
        record_audit=audit_log,
    )
    return middleware, calls, audit_log


async def test_unprotected_path_bypasses_the_limiter() -> None:
    middleware, calls, _audit_log = _build_middleware(allowed=False)

    async def call_next(request: Request) -> Response:
        return Response("ok", status_code=200)

    response = await middleware.dispatch(_request(path="/appointments"), call_next)

    assert response.status_code == 200
    assert calls == []


async def test_protected_path_under_the_limit_is_forwarded() -> None:
    middleware, calls, _audit_log = _build_middleware(allowed=True)

    async def call_next(request: Request) -> Response:
        return Response("ok", status_code=200)

    response = await middleware.dispatch(_request(path="/auth/login"), call_next)

    assert response.status_code == 200
    assert calls == ["203.0.113.9"]


async def test_protected_path_over_the_limit_is_denied_with_429() -> None:
    middleware, _, _audit_log = _build_middleware(allowed=False)

    async def call_next(request: Request) -> Response:  # pragma: no cover
        raise AssertionError("call_next must not run when rate-limited")

    response = await middleware.dispatch(_request(path="/auth/login"), call_next)

    assert response.status_code == 429


async def test_protected_path_over_the_limit_is_audited() -> None:
    """platform-hardening spec: "the throttling event MUST be auditable"."""
    middleware, _, audit_log = _build_middleware(allowed=False)

    async def call_next(request: Request) -> Response:  # pragma: no cover
        raise AssertionError("call_next must not run when rate-limited")

    response = await middleware.dispatch(_request(path="/auth/login"), call_next)

    assert response.status_code == 429
    assert len(audit_log.recorded) == 1
    entry = audit_log.recorded[0]
    assert entry.action == AuditAction.AUTH_RATE_LIMITED
    assert entry.actor_type == AuditActorType.SYSTEM
    assert entry.tenant_id == SYSTEM_TENANT_ID
    assert entry.payload["subject"] == "203.0.113.9"
    assert entry.payload["path"] == "/auth/login"


async def test_protected_path_under_the_limit_is_not_audited() -> None:
    """Triangulation: only the DENIED path writes an audit entry."""
    middleware, _, audit_log = _build_middleware(allowed=True)

    async def call_next(request: Request) -> Response:
        return Response("ok", status_code=200)

    response = await middleware.dispatch(_request(path="/auth/login"), call_next)

    assert response.status_code == 200
    assert audit_log.recorded == []


async def test_missing_client_falls_back_to_an_unknown_subject() -> None:
    middleware, calls, _audit_log = _build_middleware(allowed=True, protected_path_prefixes=frozenset({"/auth/login"}))

    async def call_next(request: Request) -> Response:
        return Response("ok", status_code=200)

    await middleware.dispatch(_request(path="/auth/login", client_host=None), call_next)

    assert calls == ["unknown"]


async def test_trust_forwarded_for_defaults_to_false_and_ignores_the_header() -> None:
    middleware, calls, _audit_log = _build_middleware(allowed=True, protected_path_prefixes=frozenset({"/auth/login"}))

    async def call_next(request: Request) -> Response:
        return Response("ok", status_code=200)

    request = _request_with_headers(
        path="/auth/login",
        client_host="203.0.113.9",
        headers=[(b"x-forwarded-for", b"198.51.100.1, 203.0.113.9")],
    )
    await middleware.dispatch(request, call_next)

    assert calls == ["203.0.113.9"]


async def test_trust_forwarded_for_uses_the_first_ip_in_the_header_when_enabled() -> None:
    middleware, calls, _audit_log = _build_middleware(
        allowed=True, protected_path_prefixes=frozenset({"/auth/login"}), trust_forwarded_for=True
    )

    async def call_next(request: Request) -> Response:
        return Response("ok", status_code=200)

    request = _request_with_headers(
        path="/auth/login",
        client_host="203.0.113.9",
        headers=[(b"x-forwarded-for", b"198.51.100.1, 203.0.113.9")],
    )
    await middleware.dispatch(request, call_next)

    assert calls == ["198.51.100.1"]


async def test_trust_forwarded_for_falls_back_to_client_host_when_header_absent() -> None:
    middleware, calls, _audit_log = _build_middleware(
        allowed=True, protected_path_prefixes=frozenset({"/auth/login"}), trust_forwarded_for=True
    )

    async def call_next(request: Request) -> Response:
        return Response("ok", status_code=200)

    await middleware.dispatch(_request(path="/auth/login", client_host="203.0.113.9"), call_next)

    assert calls == ["203.0.113.9"]


async def test_trust_forwarded_for_falls_back_to_unknown_when_header_absent_and_no_client() -> None:
    middleware, calls, _audit_log = _build_middleware(
        allowed=True, protected_path_prefixes=frozenset({"/auth/login"}), trust_forwarded_for=True
    )

    async def call_next(request: Request) -> Response:
        return Response("ok", status_code=200)

    await middleware.dispatch(_request(path="/auth/login", client_host=None), call_next)

    assert calls == ["unknown"]


async def test_audit_write_failure_does_not_prevent_the_429_response() -> None:
    """CRITICAL fix #1 (fresh-review pass): `_audit_rate_limited`'s write
    can fail (e.g. FK violation on `SYSTEM_TENANT_ID`, which has no seeded
    `tenants` row yet). That failure must never replace the intended 429
    with an unhandled 500 -- the rate-limit decision always wins."""
    middleware, _, _ = _build_middleware(allowed=False, audit_log=_FailingAuditLog())

    async def call_next(request: Request) -> Response:  # pragma: no cover
        raise AssertionError("call_next must not run when rate-limited")

    response = await middleware.dispatch(_request(path="/auth/login"), call_next)

    assert response.status_code == 429


async def test_trust_forwarded_for_strips_whitespace_around_the_first_ip() -> None:
    middleware, calls, _audit_log = _build_middleware(
        allowed=True, protected_path_prefixes=frozenset({"/auth/login"}), trust_forwarded_for=True
    )

    async def call_next(request: Request) -> Response:
        return Response("ok", status_code=200)

    request = _request_with_headers(
        path="/auth/login",
        client_host="203.0.113.9",
        headers=[(b"x-forwarded-for", b"  198.51.100.2  , 203.0.113.9")],
    )
    await middleware.dispatch(request, call_next)

    assert calls == ["198.51.100.2"]
