import uuid

import httpx

from app.main import app
from app.platform.inbound.api.access_control.dependencies import get_http_client
from app.platform.inbound.api.system_tenant import SYSTEM_TENANT_ID
from tests.platform.inbound.api.routers.conftest import (
    auth_headers,
    count_audit_rows,
    mint_access_token,
    reset_ops_bootstrap_rate_limit_budget,
    seed_reception_actor,
)

_OPERATOR_KEY_ID = "test-ops-operator"
_OPERATOR_SECRET = "test-ops-secret-at-least-32-bytes-long"
_RATE_LIMIT_OPERATOR_KEY_ID = "test-ops-ratelimit-operator"
_RATE_LIMIT_OPERATOR_SECRET = "test-ops-ratelimit-secret-at-least-32-bytes"
_OPS_BOOTSTRAP_RATE_LIMIT_MAX_ATTEMPTS = 10


def _ops_headers(*, key_id: str = _OPERATOR_KEY_ID, secret: str = _OPERATOR_SECRET) -> dict:
    return {"X-Kureha-Ops-Key": f"{key_id}.{secret}"}


def _fake_supabase_invite_transport(*, subject: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        # `SupabaseAuthAdapter.invite_user` parses the response body as the
        # bare user object (`_to_authn_result_bare`), not `{"user": {...}}`.
        return httpx.Response(200, json={"id": subject, "email": "whatever@example.com", "email_confirmed_at": None})

    return httpx.MockTransport(handler)


def _failing_supabase_invite_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "supabase down"})

    return httpx.MockTransport(handler)


def test_bootstrap_without_ops_header_is_denied(client) -> None:
    response = client.post(
        "/ops/tenants/bootstrap",
        json={"name": "No Header Clinic", "admin_email": "admin@no-header-clinic.test"},
    )

    assert response.status_code == 401
    body = response.json()
    assert body["error_code"] == "auth_required"

    assert count_audit_rows(SYSTEM_TENANT_ID, "ops.credential_denied") >= 1


def test_bootstrap_with_wrong_secret_is_denied(client) -> None:
    response = client.post(
        "/ops/tenants/bootstrap",
        json={"name": "Wrong Secret Clinic", "admin_email": "admin@wrong-secret-clinic.test"},
        headers=_ops_headers(secret="not-the-real-secret"),
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth_required"


def test_a_valid_tenant_bearer_token_alone_does_not_open_the_ops_plane(client) -> None:
    actor = seed_reception_actor(email="ops-plane-isolation@example.com")
    token = mint_access_token(
        tenant_id=actor["tenant_id"], site_id=actor["site_id"], role="reception", user_id=actor["user_id"]
    )

    response = client.post(
        "/ops/tenants/bootstrap",
        json={"name": "Plane Isolation Clinic", "admin_email": "admin@plane-isolation-clinic.test"},
        headers=auth_headers(token),
    )

    assert response.status_code == 401


def test_bootstrap_succeeds_end_to_end_and_invites_the_admin(client) -> None:
    unique = uuid.uuid4().hex
    app.dependency_overrides[get_http_client] = lambda: httpx.AsyncClient(
        base_url="https://fake-supabase.test",
        transport=_fake_supabase_invite_transport(subject=f"sub-{unique}"),
    )
    try:
        response = client.post(
            "/ops/tenants/bootstrap",
            json={"name": f"Bootstrap Clinic {unique}", "admin_email": f"admin-{unique}@bootstrap-clinic.test"},
            headers=_ops_headers(),
        )
    finally:
        app.dependency_overrides.pop(get_http_client, None)

    assert response.status_code == 201
    body = response.json()
    assert body["credential_status"] == "invited"
    assert body["tenant_id"]
    assert body["site_id"]
    assert body["admin_user_id"]
    assert body["admin_email"] == f"admin-{unique}@bootstrap-clinic.test"


def test_bootstrap_reports_invite_failed_but_still_commits_the_tenant_when_the_auth_provider_fails(client) -> None:
    unique = uuid.uuid4().hex
    app.dependency_overrides[get_http_client] = lambda: httpx.AsyncClient(
        base_url="https://fake-supabase.test", transport=_failing_supabase_invite_transport()
    )
    try:
        response = client.post(
            "/ops/tenants/bootstrap",
            json={"name": f"Invite Fail Clinic {unique}", "admin_email": f"admin-{unique}@invite-fail-clinic.test"},
            headers=_ops_headers(),
        )
    finally:
        app.dependency_overrides.pop(get_http_client, None)

    assert response.status_code == 201
    body = response.json()
    assert body["credential_status"] == "invite_failed"
    # The tenant/admin rows are already committed even though the invite failed.
    assert body["tenant_id"]
    assert body["admin_user_id"]


def test_bootstrapping_the_same_tenant_id_twice_is_a_conflict(client) -> None:
    tenant_id = str(uuid.uuid4())
    app.dependency_overrides[get_http_client] = lambda: httpx.AsyncClient(
        base_url="https://fake-supabase.test", transport=_fake_supabase_invite_transport(subject="sub-conflict")
    )
    try:
        first = client.post(
            "/ops/tenants/bootstrap",
            json={"tenant_id": tenant_id, "name": "Conflict Clinic", "admin_email": "admin@conflict-clinic.test"},
            headers=_ops_headers(),
        )
        assert first.status_code == 201

        second = client.post(
            "/ops/tenants/bootstrap",
            json={"tenant_id": tenant_id, "name": "Conflict Clinic", "admin_email": "admin2@conflict-clinic.test"},
            headers=_ops_headers(),
        )
    finally:
        app.dependency_overrides.pop(get_http_client, None)

    assert second.status_code == 409


def test_admin_invite_retry_succeeds_without_touching_provisioning(client) -> None:
    unique = uuid.uuid4().hex
    app.dependency_overrides[get_http_client] = lambda: httpx.AsyncClient(
        base_url="https://fake-supabase.test", transport=_failing_supabase_invite_transport()
    )
    try:
        bootstrap_response = client.post(
            "/ops/tenants/bootstrap",
            json={"name": f"Retry Clinic {unique}", "admin_email": f"admin-{unique}@retry-clinic.test"},
            headers=_ops_headers(),
        )
    finally:
        app.dependency_overrides.pop(get_http_client, None)
    assert bootstrap_response.status_code == 201
    bootstrap_body = bootstrap_response.json()
    assert bootstrap_body["credential_status"] == "invite_failed"

    app.dependency_overrides[get_http_client] = lambda: httpx.AsyncClient(
        base_url="https://fake-supabase.test",
        transport=_fake_supabase_invite_transport(subject=f"sub-retry-{unique}"),
    )
    try:
        retry_response = client.post(
            f"/ops/tenants/{bootstrap_body['tenant_id']}/admin-invite",
            json={
                "site_id": bootstrap_body["site_id"],
                "admin_user_id": bootstrap_body["admin_user_id"],
                "admin_email": bootstrap_body["admin_email"],
            },
            headers=_ops_headers(),
        )
    finally:
        app.dependency_overrides.pop(get_http_client, None)

    assert retry_response.status_code == 200
    assert retry_response.json()["credential_status"] == "invited"


def test_rate_limit_denies_after_the_configured_number_of_bootstrap_attempts(client) -> None:
    reset_ops_bootstrap_rate_limit_budget(_RATE_LIMIT_OPERATOR_KEY_ID)
    app.dependency_overrides[get_http_client] = lambda: httpx.AsyncClient(
        base_url="https://fake-supabase.test", transport=_failing_supabase_invite_transport()
    )
    try:
        for i in range(_OPS_BOOTSTRAP_RATE_LIMIT_MAX_ATTEMPTS):
            response = client.post(
                "/ops/tenants/bootstrap",
                json={
                    "name": f"Rate Limit Clinic {i}",
                    "admin_email": f"admin-{i}-{uuid.uuid4().hex}@rate-limit-clinic.test",
                },
                headers=_ops_headers(key_id=_RATE_LIMIT_OPERATOR_KEY_ID, secret=_RATE_LIMIT_OPERATOR_SECRET),
            )
            assert response.status_code == 201, response.json()

        over_limit_response = client.post(
            "/ops/tenants/bootstrap",
            json={
                "name": "One Too Many Clinic",
                "admin_email": f"admin-over-{uuid.uuid4().hex}@rate-limit-clinic.test",
            },
            headers=_ops_headers(key_id=_RATE_LIMIT_OPERATOR_KEY_ID, secret=_RATE_LIMIT_OPERATOR_SECRET),
        )
    finally:
        app.dependency_overrides.pop(get_http_client, None)

    assert over_limit_response.status_code == 429
    assert over_limit_response.json()["error_code"] == "rate_limited"
