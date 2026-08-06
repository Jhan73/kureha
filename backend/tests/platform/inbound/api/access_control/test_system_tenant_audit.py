"""SYSTEM_TENANT_ID must exist as a real `tenants` row, otherwise `audit_logs`'s
FK to `tenants(id)` silently swallows the write (via `record_audit_best_effort`)
for any deny that has no real tenant to attribute to (unmapped identity, missing
claims)."""

import sqlalchemy as sa
from starlette.requests import Request
from starlette.responses import Response

from app.modules.governance.audit.adapters.outbound.postgres.audit_log import PostgresAuditLog
from app.modules.identity.application.ports.driven.token_verifier import AccessTokenClaims
from app.platform.inbound.api.access_control.middleware import AccessControlMiddleware
from app.platform.inbound.api.system_tenant import SYSTEM_TENANT_ID


def _request(*, authorization: str | None = None) -> Request:
    headers = []
    if authorization is not None:
        headers.append((b"authorization", authorization.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/appointments",
        "raw_path": b"/appointments",
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


async def _unreachable_resolve_live_actor(user_id: str):  # pragma: no cover
    raise AssertionError("resolve_live_actor must not run when required claims are missing")


class _UnreachableRuntimeSession:
    async def begin(self, actor):  # pragma: no cover
        raise AssertionError("must not open a runtime session when the token is unmapped")

    async def end(self, conn, *, commit: bool) -> None:  # pragma: no cover
        raise AssertionError("must not close a runtime session that was never opened")


async def test_unmapped_token_without_tenant_claim_is_audited_against_the_system_tenant_row(
    db_conn,
) -> None:
    claims = AccessTokenClaims(sub="u1", tenant_id=None, site_id=None, role=None)
    middleware = AccessControlMiddleware(
        _dummy_app,
        token_verifier=_FakeTokenVerifier({"tok": claims}),
        resolve_live_actor=_unreachable_resolve_live_actor,
        record_audit=PostgresAuditLog(db_conn),
        runtime_session=_UnreachableRuntimeSession(),
    )

    async def call_next(request: Request) -> Response:  # pragma: no cover
        raise AssertionError("call_next must not run when denied")

    response = await middleware.dispatch(_request(authorization="Bearer tok"), call_next)

    assert response.status_code == 401

    row = (
        await db_conn.execute(
            sa.text(
                "SELECT tenant_id, action, actor_type FROM audit_logs "
                "WHERE tenant_id = :tenant_id AND action = 'auth.unmapped_identity'"
            ),
            {"tenant_id": SYSTEM_TENANT_ID},
        )
    ).one()
    assert str(row.tenant_id) == SYSTEM_TENANT_ID
    assert row.actor_type == "system"
