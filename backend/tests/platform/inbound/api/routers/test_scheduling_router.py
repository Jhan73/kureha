from datetime import datetime, timezone

from tests.platform.inbound.api.routers.conftest import (
    auth_headers,
    mint_access_token,
    seed_available_slot,
    seed_current_consent,
    seed_patient_actor,
    seed_reception_actor,
    seed_scheduled_appointment,
)

_STARTS_AT = datetime(2027, 3, 1, 9, 0, tzinfo=timezone.utc)
_ENDS_AT = datetime(2027, 3, 1, 10, 0, tzinfo=timezone.utc)
_NEW_STARTS_AT = datetime(2027, 3, 2, 9, 0, tzinfo=timezone.utc)
_NEW_ENDS_AT = datetime(2027, 3, 2, 10, 0, tzinfo=timezone.utc)


def test_schedule_appointment_succeeds_end_to_end_for_a_reception_actor(client) -> None:
    reception = seed_reception_actor(email="reception-sched@example.com")
    patient = seed_patient_actor()
    slot = seed_available_slot(reception["tenant_id"], reception["site_id"], starts_at=_STARTS_AT, ends_at=_ENDS_AT)
    # Spec `patient-self-service-portal` -> "Patient books via form" scenario's
    # own GIVEN clause: "an authenticated patient with valid consent" -- the
    # consent gate (verify-report #414 closure) now enforces this for real.
    seed_current_consent(reception["tenant_id"], reception["site_id"], patient["patient_id"])
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


def test_schedule_appointment_is_denied_when_patient_has_no_current_consent(client) -> None:
    reception = seed_reception_actor(email="reception-consent-block@example.com")
    patient = seed_patient_actor()
    slot = seed_available_slot(reception["tenant_id"], reception["site_id"], starts_at=_STARTS_AT, ends_at=_ENDS_AT)
    # Deliberately NO `seed_current_consent(...)` call -- the patient has no
    # `consents` row at all (spec scenario "Pending consent blocks form
    # submission"'s GIVEN clause: "a patient without an accepted
    # current-version consent").
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

    assert response.status_code == 403
    body = response.json()
    assert body["error_code"] == "consent_required"
    assert body["category"] == "consent-required"
    assert "correlation_id" in body


def test_reschedule_appointment_is_denied_when_patient_has_no_current_consent(client) -> None:
    reception = seed_reception_actor(email="reception-consent-reschedule@example.com")
    patient = seed_patient_actor()
    slot = seed_available_slot(reception["tenant_id"], reception["site_id"], starts_at=_STARTS_AT, ends_at=_ENDS_AT)
    new_slot = seed_available_slot(
        reception["tenant_id"], reception["site_id"], starts_at=_NEW_STARTS_AT, ends_at=_NEW_ENDS_AT
    )
    appointment_id = seed_scheduled_appointment(
        reception["tenant_id"],
        reception["site_id"],
        patient["patient_id"],
        slot["professional_id"],
        slot["availability_id"],
        starts_at=_STARTS_AT,
        ends_at=_ENDS_AT,
    )
    token = mint_access_token(
        tenant_id=reception["tenant_id"],
        site_id=reception["site_id"],
        role="reception",
        user_id=reception["user_id"],
    )

    response = client.post(
        f"/appointments/{appointment_id}/reschedule",
        json={"new_availability_id": new_slot["availability_id"]},
        headers=auth_headers(token),
    )

    assert response.status_code == 403
    body = response.json()
    assert body["error_code"] == "consent_required"
    assert body["category"] == "consent-required"


def test_cancel_appointment_is_denied_when_patient_has_no_current_consent(client) -> None:
    reception = seed_reception_actor(email="reception-consent-cancel@example.com")
    patient = seed_patient_actor()
    slot = seed_available_slot(reception["tenant_id"], reception["site_id"], starts_at=_STARTS_AT, ends_at=_ENDS_AT)
    appointment_id = seed_scheduled_appointment(
        reception["tenant_id"],
        reception["site_id"],
        patient["patient_id"],
        slot["professional_id"],
        slot["availability_id"],
        starts_at=_STARTS_AT,
        ends_at=_ENDS_AT,
    )
    token = mint_access_token(
        tenant_id=reception["tenant_id"],
        site_id=reception["site_id"],
        role="reception",
        user_id=reception["user_id"],
    )

    response = client.post(f"/appointments/{appointment_id}/cancel", headers=auth_headers(token))

    assert response.status_code == 403
    body = response.json()
    assert body["error_code"] == "consent_required"
    assert body["category"] == "consent-required"


def test_reminder_is_denied_when_patient_has_no_current_consent(client) -> None:
    reception = seed_reception_actor(email="reception-consent-reminder@example.com")
    patient = seed_patient_actor()
    slot = seed_available_slot(reception["tenant_id"], reception["site_id"], starts_at=_STARTS_AT, ends_at=_ENDS_AT)
    appointment_id = seed_scheduled_appointment(
        reception["tenant_id"],
        reception["site_id"],
        patient["patient_id"],
        slot["professional_id"],
        slot["availability_id"],
        starts_at=_STARTS_AT,
        ends_at=_ENDS_AT,
    )
    token = mint_access_token(
        tenant_id=reception["tenant_id"],
        site_id=reception["site_id"],
        role="reception",
        user_id=reception["user_id"],
    )

    response = client.post(f"/appointments/{appointment_id}/reminder", headers=auth_headers(token))

    assert response.status_code == 403
    body = response.json()
    assert body["error_code"] == "consent_required"
    assert body["category"] == "consent-required"


def test_schedule_appointment_succeeds_when_patient_has_current_consent_for_reschedule_and_cancel_flow(
    client,
) -> None:
    reception = seed_reception_actor(email="reception-consent-positive@example.com")
    patient = seed_patient_actor()
    slot = seed_available_slot(reception["tenant_id"], reception["site_id"], starts_at=_STARTS_AT, ends_at=_ENDS_AT)
    new_slot = seed_available_slot(
        reception["tenant_id"], reception["site_id"], starts_at=_NEW_STARTS_AT, ends_at=_NEW_ENDS_AT
    )
    seed_current_consent(reception["tenant_id"], reception["site_id"], patient["patient_id"])
    appointment_id = seed_scheduled_appointment(
        reception["tenant_id"],
        reception["site_id"],
        patient["patient_id"],
        slot["professional_id"],
        slot["availability_id"],
        starts_at=_STARTS_AT,
        ends_at=_ENDS_AT,
    )
    token = mint_access_token(
        tenant_id=reception["tenant_id"],
        site_id=reception["site_id"],
        role="reception",
        user_id=reception["user_id"],
    )

    reschedule_response = client.post(
        f"/appointments/{appointment_id}/reschedule",
        json={"new_availability_id": new_slot["availability_id"]},
        headers=auth_headers(token),
    )
    assert reschedule_response.status_code == 200

    cancel_response = client.post(f"/appointments/{appointment_id}/cancel", headers=auth_headers(token))
    assert cancel_response.status_code == 200


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
