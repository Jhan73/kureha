from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.schema.helpers import make_patient, make_professional, make_site, make_tenant, make_user

# SET LOCAL needs literals (no bind params); values are test-generated only.
_GUC_COLUMNS = ("tenant_id", "site_id", "role", "user_id", "patient_id", "professional_id")

# Nil UUID for unset id GUCs: always set (current_setting), always valid ::uuid.
_NIL_UUID = "00000000-0000-0000-0000-000000000000"


async def set_app_context(
    conn: AsyncConnection,
    *,
    tenant_id: str,
    role: str,
    site_id: str | None = None,
    user_id: str | None = None,
    patient_id: str | None = None,
    professional_id: str | None = None,
) -> None:
    """Set all six `app.*` GUCs for this transaction; unset ids use nil UUID."""
    values = {
        "tenant_id": tenant_id,
        "site_id": site_id,
        "role": role,
        "user_id": user_id,
        "patient_id": patient_id,
        "professional_id": professional_id,
    }
    for column in _GUC_COLUMNS:
        value = values[column]
        if value is None:
            value = _NIL_UUID  # role is a required kwarg, never None
        await conn.execute(text(f"SET LOCAL app.{column} = '{value}'"))


async def seed_tenant(conn: AsyncConnection, *, name: str = "RLS Test Clinic") -> str:
    """`tenants` has no RLS (migration 613f9ea3526f) -- no app.* context
    needed. Delegates to `tests.schema.helpers.make_tenant` (identical
    INSERT) -- the RLS suite's only extra requirement is the app.* context
    setup the other `seed_*` helpers below perform before delegating."""
    return await make_tenant(conn, name=name)


async def seed_site(conn: AsyncConnection, tenant_id: str, *, name: str = "Main Site") -> str:
    await set_app_context(conn, tenant_id=tenant_id, role="admin")
    return await make_site(conn, tenant_id, name=name)


async def seed_professional(
    conn: AsyncConnection, tenant_id: str, site_id: str, *, name: str = "Test Professional"
) -> str:
    await set_app_context(conn, tenant_id=tenant_id, site_id=site_id, role="admin")
    return await make_professional(conn, tenant_id, site_id, name=name)


async def seed_user(
    conn: AsyncConnection,
    tenant_id: str,
    site_id: str,
    *,
    role: str,
    patient_id: str | None = None,
    professional_id: str | None = None,
) -> str:
    await set_app_context(conn, tenant_id=tenant_id, site_id=site_id, role="admin")
    return await make_user(
        conn, tenant_id, site_id, role=role, patient_id=patient_id, professional_id=professional_id
    )


async def seed_patient(
    conn: AsyncConnection,
    tenant_id: str,
    site_id: str,
    *,
    document_number: str | None = None,
    name: str = "Test Patient",
) -> str:
    """Seeded via `patients_staff` (role='reception') -- always with a
    non-null `site_id` (see migration docstring's point 5: a NULL `site_id`
    would be rejected by this policy's implicit WITH CHECK)."""
    await set_app_context(conn, tenant_id=tenant_id, site_id=site_id, role="reception")
    return await make_patient(conn, tenant_id, site_id=site_id, document_number=document_number, name=name)


async def seed_availability(
    conn: AsyncConnection,
    tenant_id: str,
    site_id: str,
    professional_id: str,
    *,
    starts_at: str,
    ends_at: str,
) -> str:
    await set_app_context(conn, tenant_id=tenant_id, site_id=site_id, role="reception")
    result = await conn.execute(
        text(
            "INSERT INTO availability (tenant_id, site_id, professional_id, starts_at, ends_at) "
            "VALUES (:t, :s, :p, :starts_at, :ends_at) RETURNING id"
        ),
        {"t": tenant_id, "s": site_id, "p": professional_id, "starts_at": starts_at, "ends_at": ends_at},
    )
    return str(result.scalar_one())


async def seed_appointment(
    conn: AsyncConnection,
    tenant_id: str,
    site_id: str,
    patient_id: str,
    professional_id: str,
    availability_id: str,
    *,
    starts_at: str,
    ends_at: str,
) -> str:
    await set_app_context(conn, tenant_id=tenant_id, site_id=site_id, role="reception")
    result = await conn.execute(
        text(
            "INSERT INTO appointments "
            "(tenant_id, site_id, patient_id, professional_id, availability_id, starts_at, ends_at) "
            "VALUES (:t, :s, :patient, :prof, :avail, :starts_at, :ends_at) RETURNING id"
        ),
        {
            "t": tenant_id,
            "s": site_id,
            "patient": patient_id,
            "prof": professional_id,
            "avail": availability_id,
            "starts_at": starts_at,
            "ends_at": ends_at,
        },
    )
    return str(result.scalar_one())


async def seed_consent_policy(
    conn: AsyncConnection, tenant_id: str, *, version: str = "2026.1", is_current: bool = True
) -> None:
    await set_app_context(conn, tenant_id=tenant_id, role="admin")
    await conn.execute(
        text(
            "INSERT INTO consent_policies (tenant_id, version, document_hash, is_current) "
            "VALUES (:t, :v, 'hash', :cur)"
        ),
        {"t": tenant_id, "v": version, "cur": is_current},
    )


async def seed_consent(
    conn: AsyncConnection,
    tenant_id: str,
    site_id: str,
    patient_id: str,
    *,
    policy_version: str = "2026.1",
) -> str:
    await set_app_context(conn, tenant_id=tenant_id, site_id=site_id, role="reception")
    result = await conn.execute(
        text(
            "INSERT INTO consents "
            "(tenant_id, site_id, patient_id, policy_version, status, document_hash, channel, accepted_at) "
            "VALUES (:t, :s, :patient, :version, 'accepted', 'hash', 'web', now()) RETURNING id"
        ),
        {"t": tenant_id, "s": site_id, "patient": patient_id, "version": policy_version},
    )
    return str(result.scalar_one())


async def seed_staff_member(
    conn: AsyncConnection,
    tenant_id: str,
    site_id: str,
    *,
    name: str = "Test Staff",
    operational_role: str = "reception",
    professional_id: str | None = None,
) -> str:
    await set_app_context(conn, tenant_id=tenant_id, site_id=site_id, role="reception")
    result = await conn.execute(
        text(
            "INSERT INTO staff_members (tenant_id, site_id, professional_id, name, operational_role) "
            "VALUES (:t, :s, :prof, :n, :role) RETURNING id"
        ),
        {"t": tenant_id, "s": site_id, "prof": professional_id, "n": name, "role": operational_role},
    )
    return str(result.scalar_one())


async def seed_shift(
    conn: AsyncConnection,
    tenant_id: str,
    site_id: str,
    staff_member_id: str,
    *,
    starts_at: str,
    ends_at: str,
) -> str:
    await set_app_context(conn, tenant_id=tenant_id, site_id=site_id, role="reception")
    result = await conn.execute(
        text(
            "INSERT INTO shifts (tenant_id, site_id, staff_member_id, starts_at, ends_at) "
            "VALUES (:t, :s, :staff, :starts_at, :ends_at) RETURNING id"
        ),
        {"t": tenant_id, "s": site_id, "staff": staff_member_id, "starts_at": starts_at, "ends_at": ends_at},
    )
    return str(result.scalar_one())


async def seed_calendar_credential(conn: AsyncConnection, tenant_id: str, patient_id: str) -> str:
    await set_app_context(conn, tenant_id=tenant_id, role="patient", patient_id=patient_id)
    result = await conn.execute(
        text(
            "INSERT INTO calendar_credentials "
            "(tenant_id, patient_id, encrypted_refresh_token, nonce, wrapped_dek, key_version) "
            "VALUES (:t, :patient, :token, :nonce, :dek, 1) RETURNING id"
        ),
        {"t": tenant_id, "patient": patient_id, "token": b"ciphertext", "nonce": b"0" * 12, "dek": b"wrapped"},
    )
    return str(result.scalar_one())


async def seed_calendar_sync(
    conn: AsyncConnection, tenant_id: str, site_id: str, appointment_id: str, *, idempotency_key: str
) -> str:
    await set_app_context(conn, tenant_id=tenant_id, site_id=site_id, role="reception")
    result = await conn.execute(
        text(
            "INSERT INTO calendar_sync (tenant_id, site_id, appointment_id, idempotency_key) "
            "VALUES (:t, :s, :appt, :key) RETURNING id"
        ),
        {"t": tenant_id, "s": site_id, "appt": appointment_id, "key": idempotency_key},
    )
    return str(result.scalar_one())


async def seed_user_session(
    conn: AsyncConnection, tenant_id: str, user_id: str, *, refresh_token_hash: str
) -> str:
    await set_app_context(conn, tenant_id=tenant_id, role="admin")
    result = await conn.execute(
        text(
            "INSERT INTO user_sessions (tenant_id, user_id, refresh_token_hash, expires_at) "
            "VALUES (:t, :u, :hash, now() + interval '30 days') RETURNING id"
        ),
        {"t": tenant_id, "u": user_id, "hash": refresh_token_hash},
    )
    return str(result.scalar_one())


async def seed_user_credentials(
    conn: AsyncConnection, tenant_id: str, user_id: str, *, email: str, auth_subject: str | None = None
) -> str:
    await set_app_context(conn, tenant_id=tenant_id, role="admin")
    result = await conn.execute(
        text(
            "INSERT INTO user_credentials (tenant_id, user_id, email, auth_subject) "
            "VALUES (:t, :u, :email, :sub) RETURNING id"
        ),
        {"t": tenant_id, "u": user_id, "email": email, "sub": auth_subject},
    )
    return str(result.scalar_one())
