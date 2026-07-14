"""`PostgresUserDirectory`: `UserDirectoryPort` adapter over `users` JOIN
`user_credentials` (design.md §17.3, migration 9f1c4a7b2e3d).

**Elevated-connection contract** -- see `UserDirectoryPort`'s docstring.
Composition root (a future Phase 10 task) MUST construct this against
`app.db.engine`, never `app.db.runtime_engine`: pre-auth resolution runs
before any `app.*` GUC is known, so there is no `app_runtime`/RLS session
context to set in the first place. Same connection-ownership shape as every
other Phase 3+ postgres adapter otherwise (takes an already-open
`AsyncConnection`, does not own an engine).
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.modules.identity.domain.errors import UnmappedIdentityError
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
        # A zero-row UPDATE match does NOT raise in SQLAlchemy/Postgres (fix,
        # confirmed review finding: the previous `assert account is not
        # None` after a separate SELECT was reachable whenever `user_id` had
        # no matching `user_credentials` row -- an AssertionError, not a
        # domain error). Combine the UPDATE with the `users` JOIN needed to
        # build a full `UserAccount` into ONE round trip via a
        # data-modifying CTE (also fixes the redundant round trip this
        # method previously made calling `get_by_id` separately): the CTE's
        # RETURNING clause is empty when no row matched, so the outer SELECT
        # (and this method) naturally returns no row in that case.
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
        # NOT IMPLEMENTED, deliberately -- flagged, not silently stubbed.
        # `users.patient_id` is NOT NULL when role='patient' (CHECK
        # constraint, 8fc0dc6f958d), which FKs to `patients`, whose own
        # `name`/`document_number` columns are themselves NOT NULL and
        # UNIQUE(tenant_id, document_number) (design.md §4.1). A first-time
        # Google sign-in's `AuthnResult` carries only subject/email/
        # email_verified/provider -- no name, no DNI. Auto-provisioning a
        # real `patients` row from that alone would require either
        # inventing placeholder identity data (violates the DNI-uniqueness
        # invariant and the spirit of `patients` as verified clinical
        # identity) or a real name/DNI-collection step, which is patient
        # self-registration UX -- out of tasks.md Phase 4's scope (Phase 6
        # Tenancy/Phase 7 Scheduling territory). `Login.with_google`'s
        # orchestration for this path is implemented and unit-tested against
        # a fake `UserDirectoryPort` (tests/modules/identity/application/
        # test_login.py) so the use-case-level contract is proven; only this
        # one port method's real adapter is deferred.
        raise NotImplementedError(
            "PostgresUserDirectory.provision_patient_user is deferred: patient self-registration "
            "(name/document_number collection) does not exist yet -- see this method's docstring."
        )

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
