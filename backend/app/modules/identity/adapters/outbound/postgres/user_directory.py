from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.modules.identity.domain.errors import EmailAlreadyRegisteredError, UnmappedIdentityError
from app.modules.identity.domain.user_account import UserAccount

_SELECT = """
    SELECT u.id, u.tenant_id, u.site_id, u.role, u.status,
           uc.email, uc.auth_subject, uc.email_verified_at
    FROM user_credentials uc
    JOIN users u ON u.tenant_id = uc.tenant_id AND u.id = uc.user_id
"""

_WITH_UPDATED_CREDENTIALS = """
    WITH updated_credentials AS (
        UPDATE user_credentials
        SET auth_subject = :auth_subject,
            email_verified_at = CASE WHEN :email_verified THEN now() ELSE email_verified_at END
        WHERE tenant_id = :tenant_id AND user_id = :user_id
        RETURNING tenant_id, user_id, email, auth_subject, email_verified_at
    )
"""


class PostgresUserDirectory:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def find_by_email(self, tenant_id: str, email: str) -> UserAccount | None:
        result = await self._conn.execute(
            text(_SELECT + " WHERE uc.tenant_id = :tenant_id AND uc.email = :email"),
            {"tenant_id": tenant_id, "email": email},
        )
        return self._row_to_account(result.first())

    async def find_by_auth_subject(self, tenant_id: str, auth_subject: str) -> UserAccount | None:
        result = await self._conn.execute(
            text(_SELECT + " WHERE uc.tenant_id = :tenant_id AND uc.auth_subject = :auth_subject"),
            {"tenant_id": tenant_id, "auth_subject": auth_subject},
        )
        return self._row_to_account(result.first())

    async def get_by_id(self, tenant_id: str, user_id: str) -> UserAccount | None:
        result = await self._conn.execute(
            text(_SELECT + " WHERE uc.tenant_id = :tenant_id AND uc.user_id = :user_id"),
            {"tenant_id": tenant_id, "user_id": user_id},
        )
        return self._row_to_account(result.first())

    async def link_auth_subject(
        self, tenant_id: str, user_id: str, *, auth_subject: str, email_verified: bool
    ) -> UserAccount:
        result = await self._conn.execute(
            text(
                _WITH_UPDATED_CREDENTIALS
                + " SELECT u.id, u.tenant_id, u.site_id, u.role, u.status, "
                "updated.email, updated.auth_subject, updated.email_verified_at "
                "FROM updated_credentials updated "
                "JOIN users u ON u.tenant_id = updated.tenant_id AND u.id = updated.user_id"
            ),
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "auth_subject": auth_subject,
                "email_verified": email_verified,
            },
        )
        row = result.first()
        if row is None:
            raise UnmappedIdentityError()
        return self._row_to_account(row)

    async def provision_patient_user(
        self, tenant_id: str, *, site_id: str, email: str, auth_subject: str, email_verified: bool
    ) -> UserAccount:
        raise NotImplementedError(
            "PostgresUserDirectory.provision_patient_user is deferred: patient self-registration "
            "(name/document_number collection) does not exist yet"
        )

    async def provision_staff_user(
        self,
        tenant_id: str,
        *,
        site_id: str,
        role: str,
        email: str,
        auth_subject: str,
        email_verified: bool,
        professional_id: str | None = None,
    ) -> UserAccount:
        try:
            async with self._conn.begin_nested():
                users_result = await self._conn.execute(
                    text(
                        "INSERT INTO users (tenant_id, site_id, role, professional_id) "
                        "VALUES (:tenant_id, :site_id, :role, :professional_id) "
                        "RETURNING id"
                    ),
                    {
                        "tenant_id": tenant_id,
                        "site_id": site_id,
                        "role": role,
                        "professional_id": professional_id,
                    },
                )
                user_id = str(users_result.scalar_one())

                await self._conn.execute(
                    text(
                        "INSERT INTO user_credentials (tenant_id, user_id, email, auth_subject, email_verified_at) "
                        "VALUES (:tenant_id, :user_id, :email, :auth_subject, "
                        "CASE WHEN :email_verified THEN now() ELSE NULL END)"
                    ),
                    {
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                        "email": email,
                        "auth_subject": auth_subject,
                        "email_verified": email_verified,
                    },
                )
        except IntegrityError as exc:
            raise EmailAlreadyRegisteredError(f"email already registered: {email}") from exc

        account = await self.get_by_id(tenant_id, user_id)
        assert account is not None
        return account

    @staticmethod
    def _row_to_account(row) -> UserAccount | None:
        if row is None:
            return None
        return UserAccount(
            id=str(row.id),
            tenant_id=str(row.tenant_id),
            site_id=str(row.site_id),
            role=row.role,
            status=row.status,
            email=row.email,
            auth_subject=row.auth_subject,
            email_verified_at=row.email_verified_at,
        )
