"""Task 10.1: `/appointments/*` web-form routes against the real FastAPI app
+ real Postgres. Proves:

(a) a valid `reception` request schedules an appointment end-to-end
    (RLS-scoped connection, real `AuthorizeAction`/`PermissionService`,
    real repositories, real audit write);
(b) a `patient` actor (not granted `appointment:create` in
    `DEFAULT_DEV_ROLE_PERMISSIONS`) is denied through the REAL RBAC chain
    -- `AuthorizeAction` -> `ActionNotPermittedError` -> `errors.py`'s
    mapping -- not a hand-rolled check in the router;
(c) a domain `NotFoundError` (cancelling an appointment id that does not
    exist) comes back as the exact §21 envelope shape.

**Sync `def test_...`, not `async def`** -- see `conftest.py`'s own module
docstring for why."""

from datetime import datetime, timezone

from tests.platform.inbound.api.routers.conftest import (
    auth_headers,
    mint_access_token,
    seed_available_slot,
    seed_patient_actor,
    seed_reception_actor,
)

_STARTS_AT = datetime(2027, 3, 1, 9, 0, tzinfo=timezone.utc)
_ENDS_AT = datetime(2027, 3, 1, 10, 0, tzinfo=timezone.utc)


def test_schedule_appointment_succeeds_end_to_end_for_a_reception_actor(client) -> None:
    reception = seed_reception_actor(email="reception-sched@example.com")
    patient = seed_patient_actor()
    slot = seed_available_slot(reception["tenant_id"], reception["site_id"], starts_at=_STARTS_AT, ends_at=_ENDS_AT)
    token = mint_access_token(
        tenant_id=reception["tenant_id"],
        site_id=reception["site_id"],
        role="reception",
        user_id=reception["user_id"],
    )

    response = client.post(
        "/appointments/schedule",
        json={
            "patient_id": patient["patient_id"],
            "professional_id": slot["professional_id"],
            "site_id": reception["site_id"],
            "availability_id": slot["availability_id"],
        },
        headers=auth_headers(token),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["patient_id"] == patient["patient_id"]
    assert body["professional_id"] == slot["professional_id"]
    assert body["status"] == "scheduled"


def test_schedule_appointment_is_denied_for_a_patient_actor_via_the_real_rbac_chain(client) -> None:
    patient = seed_patient_actor()
    slot = seed_available_slot(patient["tenant_id"], patient["site_id"], starts_at=_STARTS_AT, ends_at=_ENDS_AT)
    token = mint_access_token(
        tenant_id=patient["tenant_id"], site_id=patient["site_id"], role="patient", user_id=patient["user_id"]
    )

    response = client.post(
        "/appointments/schedule",
        json={
            "patient_id": patient["patient_id"],
            "professional_id": slot["professional_id"],
            "site_id": patient["site_id"],
            "availability_id": slot["availability_id"],
        },
        headers=auth_headers(token),
    )

    assert response.status_code == 403
    body = response.json()
    assert body["error_code"] == "auth_forbidden"
    assert body["category"] == "auth"


def test_cancel_appointment_that_does_not_exist_returns_the_not_found_envelope(client) -> None:
    reception = seed_reception_actor(email="reception-cancel@example.com")
    token = mint_access_token(
        tenant_id=reception["tenant_id"],
        site_id=reception["site_id"],
        role="reception",
        user_id=reception["user_id"],
    )

    response = client.post(
        "/appointments/00000000-0000-0000-0000-000000000000/cancel",
        headers=auth_headers(token),
    )

    assert response.status_code == 404
    body = response.json()
    assert body["error_code"] == "not_found"
    assert body["category"] == "validation"
    assert "correlation_id" in body
