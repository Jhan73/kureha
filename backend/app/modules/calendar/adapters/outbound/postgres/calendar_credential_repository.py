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
        # Clear ciphertext (NOT NULL bytea → empty bytes) plus revoked_at.
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
