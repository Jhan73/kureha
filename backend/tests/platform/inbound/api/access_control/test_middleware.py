from datetime import timedelta

import pytest
from starlette.requests import Request
from starlette.responses import Response

from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.modules.identity.application.ports.driven.token_verifier import AccessTokenClaims
from app.platform.inbound.api.access_control.live_actor import LiveActor
from app.platform.inbound.api.access_control.middleware import AccessControlMiddleware
from app.platform.inbound.api.system_tenant import SYSTEM_TENANT_ID


def _request(*, path: str = "/appointments", authorization: str | None = None) -> Request:
    headers = []
    if authorization is not None:
        headers.append((b"authorization", authorization.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "headers": headers,
        "query_string": b"",
        "client": ("testclient", 123),
        "app": None,
    }
    return Request(scope)


async def _dummy_app(scope, receive, send) -> None:  # pragma: no cover - never invoked directly
    raise NotImplementedError


class _FakeTokenVerifier:
    def __init__(self, claims_by_token: dict[str, AccessTokenClaims | None]) -> None:
        self._claims_by_token = claims_by_token

    def verify(self, token: str) -> AccessTokenClaims | None:
        return self._claims_by_token.get(token)


class _FakeRuntimeSession:
    def __init__(self) -> None:
        self.begin_calls: list[LiveActor] = []
        self.end_calls: list[tuple[object, bool]] = []
        self._conn_sentinel = object()

    async def begin(self, actor: LiveActor):
        self.begin_calls.append(actor)
        return self._conn_sentinel

    async def end(self, conn, *, commit: bool) -> None:
        self.end_calls.append((conn, commit))


def _actor(**overrides) -> LiveActor:
    defaults = dict(
        user_id="u1",
        tenant_id="t1",
        site_id="s1",
        role="reception",
        status="active",
        patient_id=None,
        professional_id=None,
        staff_status=None,
    )
    defaults.update(overrides)
    return LiveActor(**defaults)


def _claims(**overrides) -> AccessTokenClaims:
    defaults = dict(sub="u1", tenant_id="t1", site_id="s1", role="reception")
    defaults.update(overrides)
    return AccessTokenClaims(**defaults)


class _FakeAuditLog:
    """Mirrors `tests/modules/identity/application/test_login.py::_FakeAuditLog`
    -- the `AuditLogPort` fake pattern already established elsewhere in the
    test suite, reused here instead of a bare callable."""

    def __init__(self) -> None:
        self.recorded: list[AuditEntry] = []

    async def record(self, entry: AuditEntry) -> str:
        self.recorded.append(entry)
        return "audit-1"


class _FailingAuditLog:
    """`AuditLogPort` fake whose `record` always raises."""

    async def record(self, entry: AuditEntry) -> str:
        raise RuntimeError("audit backend unavailable")


def _build_middleware(
    *,
    claims_by_token: dict | None = None,
    live_actors: dict | None = None,
    runtime_session: _FakeRuntimeSession | None = None,
    exempt_path_prefixes: frozenset[str] = frozenset(),
    audit_log: object | None = None,
) -> tuple[AccessControlMiddleware, list[AuditEntry], _FakeRuntimeSession]:
    audit_log = audit_log if audit_log is not None else _FakeAuditLog()

    live_actors = live_actors or {}

    async def resolve_live_actor(user_id: str) -> LiveActor | None:
        return live_actors.get(user_id)

    session = runtime_session or _FakeRuntimeSession()

    middleware = AccessControlMiddleware(
        _dummy_app,
        token_verifier=_FakeTokenVerifier(claims_by_token or {}),
        resolve_live_actor=resolve_live_actor,
        record_audit=audit_log,
        runtime_session=session,
        exempt_path_prefixes=exempt_path_prefixes,
    )
    return middleware, getattr(audit_log, "recorded", []), session


async def test_exempt_path_bypasses_auth_entirely() -> None:
    middleware, audit_entries, session = _build_middleware(exempt_path_prefixes=frozenset({"/auth/login"}))

    async def call_next(request: Request) -> Response:
        return Response("ok", status_code=200)

    response = await middleware.dispatch(_request(path="/auth/login"), call_next)

    assert response.status_code == 200
    assert audit_entries == []
    assert session.begin_calls == []


async def test_missing_authorization_header_is_denied_without_audit() -> None:
    middleware, audit_entries, session = _build_middleware()

    async def call_next(request: Request) -> Response:  # pragma: no cover - must not be reached
        raise AssertionError("call_next must not run when denied")

    response = await middleware.dispatch(_request(authorization=None), call_next)

    assert response.status_code == 401
    assert audit_entries == []


async def test_malformed_authorization_header_is_denied() -> None:
    middleware, _, _ = _build_middleware()

    async def call_next(request: Request) -> Response:  # pragma: no cover
        raise AssertionError("call_next must not run when denied")

    response = await middleware.dispatch(_request(authorization="Basic abc123"), call_next)
    assert response.status_code == 401


async def test_token_that_fails_verification_is_denied_without_audit() -> None:
    middleware, audit_entries, _ = _build_middleware(claims_by_token={})

    async def call_next(request: Request) -> Response:  # pragma: no cover
        raise AssertionError("call_next must not run when denied")

    response = await middleware.dispatch(_request(authorization="Bearer garbage"), call_next)

    assert response.status_code == 401
    assert audit_entries == []


async def test_token_missing_required_claims_is_denied_and_audited() -> None:
    middleware, audit_entries, _ = _build_middleware(
        claims_by_token={"tok": _claims(sub=None, tenant_id="t1")},
    )

    async def call_next(request: Request) -> Response:  # pragma: no cover
        raise AssertionError("call_next must not run when denied")

    response = await middleware.dispatch(_request(authorization="Bearer tok"), call_next)

    assert response.status_code == 401
    assert len(audit_entries) == 1
    assert audit_entries[0].action == AuditAction.AUTH_UNMAPPED_IDENTITY
    assert audit_entries[0].tenant_id == "t1"


async def test_token_missing_tenant_id_claim_is_denied_and_audited() -> None:
    middleware, audit_entries, _ = _build_middleware(
        claims_by_token={"tok": _claims(tenant_id=None)},
    )

    async def call_next(request: Request) -> Response:  # pragma: no cover
        raise AssertionError("call_next must not run when denied")

    response = await middleware.dispatch(_request(authorization="Bearer tok"), call_next)

    assert response.status_code == 401
    assert len(audit_entries) == 1
    entry = audit_entries[0]
    assert entry.action == AuditAction.AUTH_UNMAPPED_IDENTITY
    assert entry.actor_type == AuditActorType.SYSTEM
    assert entry.tenant_id == SYSTEM_TENANT_ID
    assert entry.payload["sub"] == "u1"


async def test_unmapped_identity_is_denied_and_audited() -> None:
    middleware, audit_entries, session = _build_middleware(
        claims_by_token={"tok": _claims(sub="ghost-user", tenant_id="t1")},
        live_actors={},
    )

    async def call_next(request: Request) -> Response:  # pragma: no cover
        raise AssertionError("call_next must not run when denied")

    response = await middleware.dispatch(_request(authorization="Bearer tok"), call_next)

    assert response.status_code == 401
    assert len(audit_entries) == 1
    assert audit_entries[0].action == AuditAction.AUTH_UNMAPPED_IDENTITY
    assert audit_entries[0].tenant_id == "t1"
    assert audit_entries[0].payload["sub"] == "ghost-user"
    assert session.begin_calls == []


async def test_inactive_actor_is_denied_and_audited() -> None:
    middleware, audit_entries, session = _build_middleware(
        claims_by_token={"tok": _claims()},
        live_actors={"u1": _actor(status="inactive")},
    )

    async def call_next(request: Request) -> Response:  # pragma: no cover
        raise AssertionError("call_next must not run when denied")

    response = await middleware.dispatch(_request(authorization="Bearer tok"), call_next)

    assert response.status_code == 403
    assert len(audit_entries) == 1
    assert audit_entries[0].action == AuditAction.AUTH_INACTIVE_ACTOR
    assert audit_entries[0].tenant_id == "t1"
    assert audit_entries[0].actor_id == "u1"
    assert session.begin_calls == []


async def test_inactive_staff_member_is_denied_even_with_active_user_status() -> None:
    middleware, audit_entries, _ = _build_middleware(
        claims_by_token={"tok": _claims()},
        live_actors={"u1": _actor(status="active", staff_status="inactive")},
    )

    async def call_next(request: Request) -> Response:  # pragma: no cover
        raise AssertionError("call_next must not run when denied")

    response = await middleware.dispatch(_request(authorization="Bearer tok"), call_next)

    assert response.status_code == 403
    assert audit_entries[0].action == AuditAction.AUTH_INACTIVE_ACTOR


async def test_active_actor_opens_runtime_session_and_forwards_request() -> None:
    middleware, audit_entries, session = _build_middleware(
        claims_by_token={"tok": _claims()},
        live_actors={"u1": _actor(status="active")},
    )

    captured_state = {}

    async def call_next(request: Request) -> Response:
        captured_state["tenant_context"] = request.state.tenant_context
        captured_state["live_actor"] = request.state.live_actor
        captured_state["db_conn"] = request.state.db_conn
        return Response("ok", status_code=200)

    response = await middleware.dispatch(_request(authorization="Bearer tok"), call_next)

    assert response.status_code == 200
    assert audit_entries == []
    assert len(session.begin_calls) == 1
    assert session.begin_calls[0].user_id == "u1"

    ctx = captured_state["tenant_context"]
    assert ctx.tenant_id == "t1"
    assert ctx.site_id == "s1"
    assert ctx.role == "reception"
    assert ctx.actor_id == "u1"
    assert captured_state["db_conn"] is session._conn_sentinel

    assert session.end_calls == [(session._conn_sentinel, True)]


async def test_downstream_5xx_response_rolls_back_the_runtime_session() -> None:
    middleware, _, session = _build_middleware(
        claims_by_token={"tok": _claims()},
        live_actors={"u1": _actor(status="active")},
    )

    async def call_next(request: Request) -> Response:
        return Response("boom", status_code=500)

    response = await middleware.dispatch(_request(authorization="Bearer tok"), call_next)

    assert response.status_code == 500
    assert session.end_calls == [(session._conn_sentinel, False)]


async def test_downstream_exception_rolls_back_and_propagates() -> None:
    middleware, _, session = _build_middleware(
        claims_by_token={"tok": _claims()},
        live_actors={"u1": _actor(status="active")},
    )

    async def call_next(request: Request) -> Response:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await middleware.dispatch(_request(authorization="Bearer tok"), call_next)

    assert session.end_calls == [(session._conn_sentinel, False)]


async def test_audit_write_failure_does_not_prevent_unmapped_identity_denial() -> None:
    middleware, _, _ = _build_middleware(
        claims_by_token={"tok": _claims(tenant_id=None)},
        audit_log=_FailingAuditLog(),
    )

    async def call_next(request: Request) -> Response:  # pragma: no cover
        raise AssertionError("call_next must not run when denied")

    response = await middleware.dispatch(_request(authorization="Bearer tok"), call_next)

    assert response.status_code == 401


async def test_audit_write_failure_does_not_prevent_inactive_actor_denial() -> None:
    middleware, _, _ = _build_middleware(
        claims_by_token={"tok": _claims()},
        live_actors={"u1": _actor(status="inactive")},
        audit_log=_FailingAuditLog(),
    )

    async def call_next(request: Request) -> Response:  # pragma: no cover
        raise AssertionError("call_next must not run when denied")

    response = await middleware.dispatch(_request(authorization="Bearer tok"), call_next)

    assert response.status_code == 403
