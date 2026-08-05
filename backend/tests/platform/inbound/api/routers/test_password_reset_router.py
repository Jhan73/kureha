"""`POST /auth/password-reset/request`/`POST /auth/password-reset/confirm`
(staff-invite / password-reset batch).

**Genuine, empirically-confirmed budget constraint, flagged not silently
worked around:** `/auth/password-reset` is listed in `app/main.py`'s
`_AUTH_RATE_LIMIT_PROTECTED_PREFIXES`, and `AuthRateLimitMiddleware`'s
`_resolve_subject` keys the IP-dimension counter by IP ALONE (not by path)
-- so every REAL HTTP call through the `client` fixture here shares the SAME
`rate_counters` row/60s-window budget as EVERY `/auth/login`/`/auth/refresh`
call anywhere else in this package (`conftest.py`'s own module docstring
flags this exact class of hazard). `test_auth_router.py` already spends 9 of
`_AUTH_RATE_LIMIT_MAX_ATTEMPTS = 10` on its own suite -- confirmed
empirically THIS session, running the FULL suite (not this file in
isolation): a second real HTTP call here already tripped a 429. This file is
therefore held to EXACTLY ONE real HTTP call total (the confirm-success
path, the highest-value proof: it is the only one of the three behaviors
this batch needs to prove that genuinely requires the real app + real
Postgres + the portal-thread's shared DB engine, see `conftest.py`'s own
docstring for why `confirm_password_reset`'s `open_elevated_connection()`
cannot safely be exercised any other way).

The other two behaviors this batch's task list calls for are covered
WITHOUT touching the shared HTTP/rate-limit budget:
- "request always returns success regardless of email existing" is tested
  below by calling the router's `request_password_reset` handler function
  DIRECTLY (bypassing ASGI/TestClient entirely) -- safe because that
  handler touches ONLY `http_client` (fully controlled here), never the
  shared DB engine, unlike `confirm_password_reset`.
- "confirm with an invalid/expired token is denied cleanly" is already
  fully covered at two lower layers: `tests/modules/identity/adapters/
  test_supabase_auth_adapter.py::test_complete_password_reset_invalid_or_expired_token_raises_generic_invalid_credentials`
  (the adapter maps Supabase's failure to `InvalidCredentialsError`) and
  `tests/modules/identity/application/test_complete_password_reset.py::
  test_completing_reset_propagates_invalid_credentials_from_an_invalid_token`
  (the use case propagates it unchanged) -- `confirm_password_reset`'s own
  router handler adds NO logic on top of letting that exception propagate
  to `errors.py`'s central handler, whose generic
  `InvalidCredentialsError -> 401 auth_required` mapping is itself already
  proven end-to-end by `test_auth_router.py`'s own wrong-password login
  tests. A third, HTTP-level repetition of the exact same mapping would add
  no new coverage while spending more of this file's already-exhausted
  shared budget.

**Fresh-review pass, this batch: 3 MORE real HTTP calls added below**
(2 for `request_password_reset`'s literal HTTP contract -- the direct-
handler-call test above only proves the USE CASE never distinguishes the
two emails, not that the ROUTE itself always answers 204; 1 for
`confirm_password_reset` with an unseeded `tenant_id`, closing a CONFIRMED
bug: `CompletePasswordReset._deny_unmapped` used to audit-write on the SAME
connection/transaction as the rest of the use case, so a caller-supplied,
never-validated `tenant_id` FK-violating that audit INSERT poisoned the
whole transaction and turned a clean 401 into an unhandled 500 -- see
`CompletePasswordReset`'s own module docstring and `IsolatedAuditLogPort`'s
docstring for the fix). Rather than re-deriving whether the package's
shared 10-per-60s budget happens to have room by the time this file runs
(fragile: it depends on real wall-clock timing across every OTHER file in
this package, not just a call count -- this file's own PREVIOUS docstring
revision above already got bitten by exactly that once), every test below
that spends real budget calls `reset_auth_ip_rate_limit_budget()`
(conftest.py) immediately before doing so, making the outcome deterministic
regardless of what ran earlier."""

import asyncio
import uuid

import httpx

from app.main import app
from app.platform.inbound.api.access_control.dependencies import get_http_client
from app.platform.inbound.api.routers.auth import PasswordResetRequest, request_password_reset
from tests.platform.inbound.api.routers.conftest import reset_auth_ip_rate_limit_budget, seed_reception_actor


class _RecordingHttpClient:
    """Fake `httpx.AsyncClient`-shaped stand-in, just enough for
    `SupabaseAuthAdapter.start_password_reset`'s single `POST` call --
    avoids needing a real `httpx.MockTransport`/event loop for a handler
    that never touches the DB, matching this file's own "no shared budget,
    no shared engine" design (see module docstring)."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def post(self, url, *, params=None, headers=None, json=None):
        self.calls.append({"url": url, "json": json})

        class _Resp:
            status_code = 200

            def json(self_inner):
                return {}

        return _Resp()


def test_password_reset_request_always_returns_success_regardless_of_whether_the_email_exists() -> None:
    """Calls the router HANDLER FUNCTION directly (not through the ASGI
    app/`client` fixture) -- see module docstring for why this is both safe
    (no shared DB engine involved) and outside the rate-limit budget
    entirely. Two calls, one per email, both must complete without raising
    -- `start_password_reset`'s own anti-enumeration contract."""
    http_client = _RecordingHttpClient()

    async def _run() -> None:
        await request_password_reset(
            PasswordResetRequest(tenant_id="t1", email="existing@example.com"), http_client=http_client
        )
        await request_password_reset(
            PasswordResetRequest(tenant_id="t1", email="never-registered@example.com"), http_client=http_client
        )

    asyncio.run(_run())  # must not raise for either email

    assert [call["json"]["email"] for call in http_client.calls] == [
        "existing@example.com",
        "never-registered@example.com",
    ]


def test_password_reset_confirm_with_a_valid_token_mints_working_tokens(client) -> None:
    """(The ONE real HTTP call this file spends, see module docstring.)
    Proves `AuthPort.complete_password_reset` -> resolve by
    `find_by_auth_subject`/`find_by_email` -> mint access+refresh, end to
    end against the real app + real Postgres. Resolves via the
    `find_by_email` fallback (this actor has no `auth_subject` linked yet),
    matching `CompletePasswordReset`'s own documented resolution order."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert request.url.path == "/auth/v1/user"
        return httpx.Response(
            200,
            json={
                "id": "supabase-reset-sub-1",
                "email": "reset-confirm-valid@example.com",
                "email_confirmed_at": "2026-01-01T00:00:00Z",
            },
        )

    actor = seed_reception_actor(email="reset-confirm-valid@example.com")

    reset_auth_ip_rate_limit_budget()
    app.dependency_overrides[get_http_client] = lambda: httpx.AsyncClient(
        base_url="https://fake-supabase.test", transport=httpx.MockTransport(handler)
    )
    try:
        response = client.post(
            "/auth/password-reset/confirm",
            json={
                "tenant_id": actor["tenant_id"],
                "recovery_token": "valid-recovery-token",
                "new_password": "new-correct-horse",
            },
        )
    finally:
        app.dependency_overrides.pop(get_http_client, None)

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == actor["user_id"]
    assert body["role"] == "reception"
    assert body["access_token"]
    assert body["refresh_token"]


def test_password_reset_request_returns_204_over_real_http_for_an_existing_and_a_nonexistent_email(client) -> None:
    """Fresh-review pass, additive coverage (this batch): the direct-
    handler-call test above proves the USE CASE never distinguishes the two
    cases, but bypasses ASGI entirely -- it cannot prove the ROUTE itself
    (path wiring, `status_code=204` on the decorator, the real
    `AccessControlMiddleware`/`AuthRateLimitMiddleware` stack) actually
    answers 204 for both. `start_password_reset` never inspects the mocked
    response's status code (see `SupabaseAuthAdapter.start_password_reset`'s
    own docstring), so a bare 200 is enough for the fake transport here."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    actor = seed_reception_actor(email="reset-request-real-http@example.com")

    reset_auth_ip_rate_limit_budget()
    app.dependency_overrides[get_http_client] = lambda: httpx.AsyncClient(
        base_url="https://fake-supabase.test", transport=httpx.MockTransport(handler)
    )
    try:
        existing_response = client.post(
            "/auth/password-reset/request",
            json={"tenant_id": actor["tenant_id"], "email": actor["email"]},
        )
        nonexistent_response = client.post(
            "/auth/password-reset/request",
            json={"tenant_id": actor["tenant_id"], "email": "never-registered-real-http@example.com"},
        )
    finally:
        app.dependency_overrides.pop(get_http_client, None)

    assert existing_response.status_code == 204
    assert nonexistent_response.status_code == 204


def test_password_reset_confirm_with_an_unseeded_tenant_id_denies_cleanly_without_a_500(client) -> None:
    """Fresh-review pass, CONFIRMED bug closed by this test (this batch):
    `CompletePasswordReset._deny_unmapped` used to write the
    `AUTH_UNMAPPED_IDENTITY` audit entry through a plain `AuditLogPort`
    bound to the SAME connection/transaction as `user_directory`/
    `session_store` -- `tenant_id` here is caller-supplied and never
    validated against a real `tenants` row (`PasswordResetConfirmRequest
    .tenant_id`, see `routers/auth.py`'s own docstring). A genuinely
    unseeded `tenant_id` (a fresh, never-persisted UUID -- `_migrated_schema`
    seeds no tenants at all) makes the audit INSERT itself violate
    `audit_logs`' real tenant FK; on that SHARED connection the resulting
    `IntegrityError` used to propagate straight through as an unhandled 500
    instead of the intended `UnmappedIdentityError`/401.

    Mocks Supabase to return a genuinely SUCCESSFUL, resolvable identity
    (not an invalid/expired token -- that would raise `InvalidCredentialsError`
    BEFORE `_deny_unmapped` is ever reached at all, proving nothing about
    THIS fix) so `CompletePasswordReset.execute` actually reaches
    `find_by_auth_subject`/`find_by_email` (both correctly return `None` for
    an unseeded tenant), then `_deny_unmapped`, then its now-isolated audit
    write -- exercising the exact FK-violation shape the original bug
    reproduced, end to end against the real app + real Postgres."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "supabase-sub-unseeded-tenant",
                "email": "unseeded-tenant-reset@example.com",
                "email_confirmed_at": "2026-01-01T00:00:00Z",
            },
        )

    unseeded_tenant_id = str(uuid.uuid4())

    reset_auth_ip_rate_limit_budget()
    app.dependency_overrides[get_http_client] = lambda: httpx.AsyncClient(
        base_url="https://fake-supabase.test", transport=httpx.MockTransport(handler)
    )
    try:
        response = client.post(
            "/auth/password-reset/confirm",
            json={
                "tenant_id": unseeded_tenant_id,
                "recovery_token": "valid-shaped-recovery-token",
                "new_password": "new-correct-horse",
            },
        )
    finally:
        app.dependency_overrides.pop(get_http_client, None)

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth_required"
