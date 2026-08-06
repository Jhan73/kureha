import json

import httpx
import sqlalchemy as sa

from app.config import settings
from app.main import app
from app.platform.inbound.api.access_control.dependencies import get_http_client
from tests.platform.inbound.api.routers.conftest import (
    _committing_conn,
    _run,
    auth_headers,
    mint_access_token,
    seed_patient_actor,
    seed_reception_actor,
)

_SERVICE_ROLE_KEY = "test-service-role-key"


def _fake_invite_transport(*, subject: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/auth/v1/invite"
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={"id": subject, "email": body["email"], "email_confirmed_at": None},
        )

    return httpx.MockTransport(handler)


def _existing_user_credentials_email(tenant_id: str, site_id: str, *, email: str) -> None:
    async def _seed() -> None:
        async with _committing_conn() as conn:
            user_result = await conn.execute(
                sa.text(
                    "INSERT INTO users (tenant_id, site_id, role) VALUES (:t, :s, 'reception') RETURNING id"
                ),
                {"t": tenant_id, "s": site_id},
            )
            user_id = str(user_result.scalar_one())
            await conn.execute(
                sa.text(
                    "INSERT INTO user_credentials (tenant_id, user_id, email) VALUES (:t, :u, :e)"
                ),
                {"t": tenant_id, "u": user_id, "e": email},
            )

    _run(_seed())


def test_register_staff_succeeds_end_to_end_and_creates_a_usable_identity(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "supabase_service_role_key", _SERVICE_ROLE_KEY)
    actor = seed_reception_actor(email="reception-registrar1@example.com")
    token = mint_access_token(
        tenant_id=actor["tenant_id"], site_id=actor["site_id"], role="reception", user_id=actor["user_id"]
    )

    app.dependency_overrides[get_http_client] = lambda: httpx.AsyncClient(
        base_url="https://fake-supabase.test",
        transport=_fake_invite_transport(subject="supabase-invited-sub-1"),
    )
    try:
        response = client.post(
            "/staff/register",
            json={
                "site_id": actor["site_id"],
                "name": "New Receptionist",
                "operational_role": "reception",
                "email": "new-receptionist@example.com",
            },
            headers=auth_headers(token),
        )
    finally:
        app.dependency_overrides.pop(get_http_client, None)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new-receptionist@example.com"
    assert body["operational_role"] == "reception"
    assert body["staff_member_id"]
    assert body["user_id"]

    # The newly-provisioned identity genuinely landed in Postgres --
    # verified directly at the DB layer (NOT via a real `/auth/login` call:
    # that endpoint shares the `/auth/*` IP-dimension rate-limit budget with
    # `test_auth_router.py`'s own suite, see this file's own module
    # docstring and `conftest.py`'s -- a DB-level assertion proves the same
    # fact without touching that shared, timing-sensitive budget at all).
    async def _row_exists() -> bool:
        async with _committing_conn() as conn:
            result = await conn.execute(
                sa.text(
                    "SELECT uc.auth_subject, u.role, u.status FROM user_credentials uc "
                    "JOIN users u ON u.tenant_id = uc.tenant_id AND u.id = uc.user_id "
                    "WHERE uc.tenant_id = :t AND uc.user_id = :u"
                ),
                {"t": actor["tenant_id"], "u": body["user_id"]},
            )
            row = result.one()
            return row.auth_subject == "supabase-invited-sub-1" and row.role == "reception" and row.status == "active"

    assert _run(_row_exists())

    # The staff_members row (RegisterStaff's own, unchanged responsibility)
    # was created and linked to the SAME new user_id.
    async def _staff_member_linked() -> bool:
        async with _committing_conn() as conn:
            result = await conn.execute(
                sa.text("SELECT user_id FROM staff_members WHERE tenant_id = :t AND id = :s"),
                {"t": actor["tenant_id"], "s": body["staff_member_id"]},
            )
            return str(result.scalar_one()) == body["user_id"]

    assert _run(_staff_member_linked())


def test_register_staff_with_an_already_registered_email_is_rejected_without_inviting(client) -> None:
    actor = seed_reception_actor(email="reception-registrar2@example.com")
    token = mint_access_token(
        tenant_id=actor["tenant_id"], site_id=actor["site_id"], role="reception", user_id=actor["user_id"]
    )
    _existing_user_credentials_email(actor["tenant_id"], actor["site_id"], email="already-here@example.com")

    invited = {"called": False}

    def handler(request: httpx.Request) -> httpx.Response:
        invited["called"] = True
        return httpx.Response(200, json={"id": "should-not-happen", "email": "already-here@example.com"})

    app.dependency_overrides[get_http_client] = lambda: httpx.AsyncClient(
        base_url="https://fake-supabase.test", transport=httpx.MockTransport(handler)
    )
    try:
        response = client.post(
            "/staff/register",
            json={
                "site_id": actor["site_id"],
                "name": "Duplicate",
                "operational_role": "reception",
                "email": "already-here@example.com",
            },
            headers=auth_headers(token),
        )
    finally:
        app.dependency_overrides.pop(get_http_client, None)

    assert response.status_code == 409
    body = response.json()
    assert body["error_code"] == "conflict"
    assert invited["called"] is False


def test_register_staff_is_denied_for_a_patient_actor(client) -> None:
    actor = seed_patient_actor()
    token = mint_access_token(
        tenant_id=actor["tenant_id"], site_id=actor["site_id"], role="patient", user_id=actor["user_id"]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Supabase must never be called for a denied request")

    app.dependency_overrides[get_http_client] = lambda: httpx.AsyncClient(
        base_url="https://fake-supabase.test", transport=httpx.MockTransport(handler)
    )
    try:
        response = client.post(
            "/staff/register",
            json={
                "site_id": actor["site_id"],
                "name": "Should Not Exist",
                "operational_role": "reception",
                "email": "denied-actor@example.com",
            },
            headers=auth_headers(token),
        )
    finally:
        app.dependency_overrides.pop(get_http_client, None)

    assert response.status_code == 403

    async def _no_row_created() -> bool:
        async with _committing_conn() as conn:
            result = await conn.execute(
                sa.text(
                    "SELECT count(*) FROM user_credentials WHERE tenant_id = :t AND email = :e"
                ),
                {"t": actor["tenant_id"], "e": "denied-actor@example.com"},
            )
            return result.scalar_one() == 0

    assert _run(_no_row_created())
