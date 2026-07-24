"""`PostgresCalendarCredentialRepository`: `CalendarCredentialRepositoryPort`
adapter over `calendar_credentials` (design.md §4.4/§7.3/§7.4, migration
00d985a7bfa5).

Takes an already-open `AsyncConnection` rather than owning an engine, same
pattern every other postgres adapter in this codebase follows. The
composition root (tasks.md task 10.2) MUST construct this against a
connection with `app.role='patient'` + matching `app.patient_id` already
set via `SET LOCAL` -- see the port's own module docstring for why (the
ONLY policy on this table, `calendar_credentials_self`, requires exactly
that).

`save` upserts on `(tenant_id, patient_id)` (`UNIQUE`, migration
00d985a7bfa5) -- a patient reconnecting replaces the previous ciphertext AND
clears any prior `revoked_at` (reconnecting after a revoke is a normal,
expected flow, not an error)."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.modules.calendar.domain.calendar_credential import EncryptedCredentialRecord
from app.modules.calendar.domain.encrypted_secret import EncryptedSecret

_SELECT = (
    "SELECT id, tenant_id, patient_id, encrypted_refresh_token, nonce, wrapped_dek, key_version, "
    "scope, connected_at, revoked_at FROM calendar_credentials"
)


class PostgresCalendarCredentialRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def get(self, tenant_id: str, patient_id: str) -> EncryptedCredentialRecord | None:
        result = await self._conn.execute(
            text(_SELECT + " WHERE tenant_id = :tenant_id AND patient_id = :patient_id"),
            {"tenant_id": tenant_id, "patient_id": patient_id},
        )
        row = result.first()
        return self._row_to_record(row) if row is not None else None

    async def save(
        self, tenant_id: str, patient_id: str, secret: EncryptedSecret, *, scope: str
    ) -> EncryptedCredentialRecord:
        result = await self._conn.execute(
            text(
                "INSERT INTO calendar_credentials "
                "(tenant_id, patient_id, encrypted_refresh_token, nonce, wrapped_dek, key_version, scope) "
                "VALUES (:tenant_id, :patient_id, :ciphertext, :nonce, :wrapped_dek, :key_version, :scope) "
                "ON CONFLICT (tenant_id, patient_id) DO UPDATE SET "
                "encrypted_refresh_token = EXCLUDED.encrypted_refresh_token, "
                "nonce = EXCLUDED.nonce, wrapped_dek = EXCLUDED.wrapped_dek, "
                "key_version = EXCLUDED.key_version, scope = EXCLUDED.scope, revoked_at = NULL "
                "RETURNING id, tenant_id, patient_id, encrypted_refresh_token, nonce, wrapped_dek, key_version, "
                "scope, connected_at, revoked_at"
            ),
            {
                "tenant_id": tenant_id,
                "patient_id": patient_id,
                "ciphertext": secret.ciphertext,
                "nonce": secret.nonce,
                "wrapped_dek": secret.wrapped_dek,
                "key_version": secret.key_version,
                "scope": scope,
            },
        )
        row = result.one()
        return self._row_to_record(row)

    async def revoke(self, tenant_id: str, patient_id: str) -> None:
        # Task 10.4 fix (kureha-mvp PR9 verify finding): design.md §7.3 --
        # "En rollback/desactivacion: revoked_at + borrado del token cifrado"
        # -- and this port's own docstring both require the ciphertext
        # itself to be erased, not just `revoked_at` flipped. The three
        # `bytea` columns are `NOT NULL` (migration 00d985a7bfa5), so
        # "borrado" means zero-length bytes here, not `NULL` -- a
        # subsequent `save()` (reconnect) overwrites them with a fresh
        # secret regardless, same as it already clears `revoked_at`.
        await self._conn.execute(
            text(
                "UPDATE calendar_credentials SET revoked_at = now(), "
                "encrypted_refresh_token = '', nonce = '', wrapped_dek = '' "
                "WHERE tenant_id = :tenant_id AND patient_id = :patient_id"
            ),
            {"tenant_id": tenant_id, "patient_id": patient_id},
        )

    @staticmethod
    def _row_to_record(row) -> EncryptedCredentialRecord:
        return EncryptedCredentialRecord(
            id=str(row.id),
            tenant_id=str(row.tenant_id),
            patient_id=str(row.patient_id),
            secret=EncryptedSecret(
                ciphertext=bytes(row.encrypted_refresh_token),
                nonce=bytes(row.nonce),
                wrapped_dek=bytes(row.wrapped_dek),
                key_version=row.key_version,
            ),
            scope=row.scope,
            connected_at=row.connected_at,
            revoked_at=row.revoked_at,
        )
