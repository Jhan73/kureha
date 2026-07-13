"""Task 2.7: calendar_credentials, calendar_sync (design.md §4.4, §7).

`calendar_credentials` is tenant-wide identity like `patients` (one Google
connection per patient, not per site). `calendar_sync` carries the
deterministic `idempotency_key` (ADR-18, §7.6): retries of `events.insert`
reuse the same key, so `UNIQUE(tenant_id, idempotency_key)` is the
constraint that actually guarantees "exactly one `google_event_id` per
appointment after any number of retries".
"""

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from tests.schema.helpers import expect_violation, make_patient, make_professional, make_site, make_tenant

T0 = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)


async def make_appointment(conn, tenant_id, site_id, patient_id, professional_id) -> str:
    availability_id = (
        await conn.execute(
            sa.text(
                "INSERT INTO availability (tenant_id, site_id, professional_id, starts_at, ends_at) "
                "VALUES (:tenant_id, :site_id, :professional_id, :starts_at, :ends_at) RETURNING id"
            ),
            {
                "tenant_id": tenant_id,
                "site_id": site_id,
                "professional_id": professional_id,
                "starts_at": T0,
                "ends_at": T0 + timedelta(hours=1),
            },
        )
    ).scalar_one()
    result = await conn.execute(
        sa.text(
            "INSERT INTO appointments "
            "(tenant_id, site_id, patient_id, professional_id, availability_id, starts_at, ends_at) "
            "VALUES (:tenant_id, :site_id, :patient_id, :professional_id, :availability_id, "
            " :starts_at, :ends_at) RETURNING id"
        ),
        {
            "tenant_id": tenant_id,
            "site_id": site_id,
            "patient_id": patient_id,
            "professional_id": professional_id,
            "availability_id": availability_id,
            "starts_at": T0,
            "ends_at": T0 + timedelta(hours=1),
        },
    )
    return str(result.scalar_one())


async def make_calendar_credential(conn, tenant_id, patient_id) -> str:
    result = await conn.execute(
        sa.text(
            "INSERT INTO calendar_credentials "
            "(tenant_id, patient_id, encrypted_refresh_token, nonce, wrapped_dek, key_version) "
            "VALUES (:tenant_id, :patient_id, :token, :nonce, :dek, 1) RETURNING id"
        ),
        {
            "tenant_id": tenant_id,
            "patient_id": patient_id,
            "token": b"ciphertext",
            "nonce": b"0" * 12,
            "dek": b"wrapped",
        },
    )
    return str(result.scalar_one())


async def test_calendar_credentials_scope_defaults_to_calendar_events(db_conn, tenant_id) -> None:
    patient_id = await make_patient(db_conn, tenant_id)
    credential_id = await make_calendar_credential(db_conn, tenant_id, patient_id)

    row = (
        await db_conn.execute(
            sa.text("SELECT scope FROM calendar_credentials WHERE id = :id"), {"id": credential_id}
        )
    ).one()
    assert row.scope == "https://www.googleapis.com/auth/calendar.events"


async def test_calendar_credentials_one_per_patient_per_tenant(db_conn, tenant_id) -> None:
    patient_id = await make_patient(db_conn, tenant_id)
    await make_calendar_credential(db_conn, tenant_id, patient_id)

    async with expect_violation(db_conn, IntegrityError):
        await make_calendar_credential(db_conn, tenant_id, patient_id)


async def test_calendar_credentials_patient_id_must_belong_to_same_tenant(db_conn) -> None:
    tenant_a = await make_tenant(db_conn)
    tenant_b = await make_tenant(db_conn)
    patient_of_b = await make_patient(db_conn, tenant_b)

    async with expect_violation(db_conn):
        await make_calendar_credential(db_conn, tenant_a, patient_of_b)


async def test_calendar_sync_status_defaults_to_pending(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    professional_id = await make_professional(db_conn, tenant_id, site_id)
    patient_id = await make_patient(db_conn, tenant_id, site_id=site_id)
    appointment_id = await make_appointment(db_conn, tenant_id, site_id, patient_id, professional_id)

    result = await db_conn.execute(
        sa.text(
            "INSERT INTO calendar_sync (tenant_id, site_id, appointment_id, idempotency_key) "
            "VALUES (:tenant_id, :site_id, :appointment_id, :key) RETURNING id"
        ),
        {
            "tenant_id": tenant_id,
            "site_id": site_id,
            "appointment_id": appointment_id,
            "key": f"kureha{appointment_id.replace('-', '')}",
        },
    )
    sync_id = result.scalar_one()

    row = (
        await db_conn.execute(
            sa.text("SELECT sync_status, attempts FROM calendar_sync WHERE id = :id"), {"id": sync_id}
        )
    ).one()
    assert row.sync_status == "pending"
    assert row.attempts == 0


async def test_calendar_sync_rejects_unknown_status(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    professional_id = await make_professional(db_conn, tenant_id, site_id)
    patient_id = await make_patient(db_conn, tenant_id, site_id=site_id)
    appointment_id = await make_appointment(db_conn, tenant_id, site_id, patient_id, professional_id)

    async with expect_violation(db_conn):
        await db_conn.execute(
            sa.text(
                "INSERT INTO calendar_sync (tenant_id, site_id, appointment_id, idempotency_key, sync_status) "
                "VALUES (:tenant_id, :site_id, :appointment_id, :key, 'bogus')"
            ),
            {
                "tenant_id": tenant_id,
                "site_id": site_id,
                "appointment_id": appointment_id,
                "key": "kureha-x",
            },
        )


async def test_calendar_sync_one_row_per_appointment(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    professional_id = await make_professional(db_conn, tenant_id, site_id)
    patient_id = await make_patient(db_conn, tenant_id, site_id=site_id)
    appointment_id = await make_appointment(db_conn, tenant_id, site_id, patient_id, professional_id)

    await db_conn.execute(
        sa.text(
            "INSERT INTO calendar_sync (tenant_id, site_id, appointment_id, idempotency_key) "
            "VALUES (:tenant_id, :site_id, :appointment_id, :key)"
        ),
        {"tenant_id": tenant_id, "site_id": site_id, "appointment_id": appointment_id, "key": "kureha-1"},
    )

    async with expect_violation(db_conn, IntegrityError):
        await db_conn.execute(
            sa.text(
                "INSERT INTO calendar_sync (tenant_id, site_id, appointment_id, idempotency_key) "
                "VALUES (:tenant_id, :site_id, :appointment_id, :key)"
            ),
            {
                "tenant_id": tenant_id,
                "site_id": site_id,
                "appointment_id": appointment_id,
                "key": "kureha-2",
            },
        )


async def test_calendar_sync_idempotency_key_unique_within_tenant(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    professional_a = await make_professional(db_conn, tenant_id, site_id, name="A")
    professional_b = await make_professional(db_conn, tenant_id, site_id, name="B")
    patient_a = await make_patient(db_conn, tenant_id, site_id=site_id)
    patient_b = await make_patient(db_conn, tenant_id, site_id=site_id)
    appointment_a = await make_appointment(db_conn, tenant_id, site_id, patient_a, professional_a)
    appointment_b = await make_appointment(db_conn, tenant_id, site_id, patient_b, professional_b)

    await db_conn.execute(
        sa.text(
            "INSERT INTO calendar_sync (tenant_id, site_id, appointment_id, idempotency_key) "
            "VALUES (:tenant_id, :site_id, :appointment_id, 'kureha-dup')"
        ),
        {"tenant_id": tenant_id, "site_id": site_id, "appointment_id": appointment_a},
    )

    async with expect_violation(db_conn, IntegrityError):
        await db_conn.execute(
            sa.text(
                "INSERT INTO calendar_sync (tenant_id, site_id, appointment_id, idempotency_key) "
                "VALUES (:tenant_id, :site_id, :appointment_id, 'kureha-dup')"
            ),
            {"tenant_id": tenant_id, "site_id": site_id, "appointment_id": appointment_b},
        )


async def test_calendar_sync_appointment_id_must_belong_to_same_tenant(db_conn) -> None:
    tenant_a = await make_tenant(db_conn)
    tenant_b = await make_tenant(db_conn)
    site_a = await make_site(db_conn, tenant_a)
    site_b = await make_site(db_conn, tenant_b)
    professional_b = await make_professional(db_conn, tenant_b, site_b)
    patient_b = await make_patient(db_conn, tenant_b, site_id=site_b)
    appointment_of_b = await make_appointment(db_conn, tenant_b, site_b, patient_b, professional_b)

    async with expect_violation(db_conn):
        await db_conn.execute(
            sa.text(
                "INSERT INTO calendar_sync (tenant_id, site_id, appointment_id, idempotency_key) "
                "VALUES (:tenant_id, :site_id, :appointment_id, 'kureha-cross')"
            ),
            {"tenant_id": tenant_a, "site_id": site_a, "appointment_id": appointment_of_b},
        )
