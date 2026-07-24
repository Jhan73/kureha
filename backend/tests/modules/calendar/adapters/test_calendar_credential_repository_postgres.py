"""Task 9.4: `PostgresCalendarCredentialRepository` -- `CalendarCredentialRepositoryPort`
adapter over `calendar_credentials` (design.md §4.4/§7.3/§7.4, migration
00d985a7bfa5). Uses `rls_conn` (the `app_runtime`/RLS-enforced connection)
scoped as `role='patient'` -- `calendar_credentials_self` is the ONLY policy
on this table (migration 613f9ea3526f), see the port's own module docstring
for why."""

import pytest

from tests.rls.helpers import seed_patient, seed_site, seed_tenant, set_app_context

from app.modules.calendar.adapters.outbound.postgres.calendar_credential_repository import (
    PostgresCalendarCredentialRepository,
)
from app.modules.calendar.domain.encrypted_secret import EncryptedSecret


async def _seed_patient(rls_conn) -> tuple[str, str]:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    patient_id = await seed_patient(rls_conn, tenant_id, site_id)
    return tenant_id, patient_id


def _secret(*, ciphertext: bytes = b"cipher") -> EncryptedSecret:
    return EncryptedSecret(ciphertext=ciphertext, nonce=b"n" * 12, wrapped_dek=b"wrapped", key_version=1)


async def test_get_returns_none_when_nothing_connected(rls_conn) -> None:
    tenant_id, patient_id = await _seed_patient(rls_conn)
    await set_app_context(rls_conn, tenant_id=tenant_id, role="patient", patient_id=patient_id)
    repository = PostgresCalendarCredentialRepository(rls_conn)

    assert await repository.get(tenant_id, patient_id) is None


async def test_save_then_get_round_trips_the_encrypted_secret(rls_conn) -> None:
    tenant_id, patient_id = await _seed_patient(rls_conn)
    await set_app_context(rls_conn, tenant_id=tenant_id, role="patient", patient_id=patient_id)
    repository = PostgresCalendarCredentialRepository(rls_conn)

    saved = await repository.save(tenant_id, patient_id, _secret(), scope="calendar.events")
    fetched = await repository.get(tenant_id, patient_id)

    assert saved.patient_id == patient_id
    assert saved.is_revoked is False
    assert fetched is not None
    assert fetched.secret.ciphertext == b"cipher"
    assert fetched.secret.nonce == b"n" * 12
    assert fetched.secret.wrapped_dek == b"wrapped"
    assert fetched.secret.key_version == 1
    assert fetched.scope == "calendar.events"


async def test_save_again_upserts_and_replaces_the_previous_secret(rls_conn) -> None:
    tenant_id, patient_id = await _seed_patient(rls_conn)
    await set_app_context(rls_conn, tenant_id=tenant_id, role="patient", patient_id=patient_id)
    repository = PostgresCalendarCredentialRepository(rls_conn)
    await repository.save(tenant_id, patient_id, _secret(ciphertext=b"old"), scope="calendar.events")

    await repository.save(tenant_id, patient_id, _secret(ciphertext=b"new"), scope="calendar.events")
    fetched = await repository.get(tenant_id, patient_id)

    assert fetched.secret.ciphertext == b"new"


async def test_revoke_marks_the_credential_revoked(rls_conn) -> None:
    tenant_id, patient_id = await _seed_patient(rls_conn)
    await set_app_context(rls_conn, tenant_id=tenant_id, role="patient", patient_id=patient_id)
    repository = PostgresCalendarCredentialRepository(rls_conn)
    await repository.save(tenant_id, patient_id, _secret(), scope="calendar.events")

    await repository.revoke(tenant_id, patient_id)
    fetched = await repository.get(tenant_id, patient_id)

    assert fetched.is_revoked is True


async def test_reconnecting_after_revoke_clears_revoked_at(rls_conn) -> None:
    tenant_id, patient_id = await _seed_patient(rls_conn)
    await set_app_context(rls_conn, tenant_id=tenant_id, role="patient", patient_id=patient_id)
    repository = PostgresCalendarCredentialRepository(rls_conn)
    await repository.save(tenant_id, patient_id, _secret(), scope="calendar.events")
    await repository.revoke(tenant_id, patient_id)

    await repository.save(tenant_id, patient_id, _secret(ciphertext=b"fresh"), scope="calendar.events")
    fetched = await repository.get(tenant_id, patient_id)

    assert fetched.is_revoked is False
    assert fetched.secret.ciphertext == b"fresh"


async def test_revoke_also_erases_the_encrypted_token_columns(rls_conn) -> None:
    """Task 10.4 (kureha-mvp PR9 verify finding): design.md §7.3 -- "En
    rollback/desactivacion: revoked_at + borrado del token cifrado" -- and
    the port's own docstring -- "Sets revoked_at and clears the encrypted
    token" -- both require `revoke()` to erase the ciphertext, not just flip
    `revoked_at`. Before this fix, `revoke()` only set `revoked_at`, leaving
    `encrypted_refresh_token`/`nonce`/`wrapped_dek` fully intact and
    recoverable in the same row."""
    tenant_id, patient_id = await _seed_patient(rls_conn)
    await set_app_context(rls_conn, tenant_id=tenant_id, role="patient", patient_id=patient_id)
    repository = PostgresCalendarCredentialRepository(rls_conn)
    await repository.save(tenant_id, patient_id, _secret(), scope="calendar.events")

    await repository.revoke(tenant_id, patient_id)
    fetched = await repository.get(tenant_id, patient_id)

    assert fetched.is_revoked is True
    assert fetched.secret.ciphertext == b""
    assert fetched.secret.nonce == b""
    assert fetched.secret.wrapped_dek == b""
