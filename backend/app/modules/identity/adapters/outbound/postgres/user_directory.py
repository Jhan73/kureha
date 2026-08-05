"""`PostgresUserDirectory`: `UserDirectoryPort` adapter over `users` JOIN
`user_credentials` (design.md §17.3, migration 9f1c4a7b2e3d).

**Elevated-connection contract** -- see `UserDirectoryPort`'s docstring.
Composition root (a future Phase 10 task) MUST construct this against
`app.db.engine`, never `app.db.runtime_engine`: pre-auth resolution runs
before any `app.*` GUC is known, so there is no `app_runtime`/RLS session
context to set in the first place. Same connection-ownership shape as every
other Phase 3+ postgres adapter otherwise (takes an already-open
`AsyncConnection`, does not own an engine).

**`provision_staff_user` (staff-invite batch) is a DELIBERATE, DOCUMENTED
EXCEPTION to the elevated-connection contract above.** Every other method on
this class exists to resolve identity BEFORE any `app.*` GUC/`TenantContext`
exists (pre-auth). `provision_staff_user` is the opposite: it only ever runs
INSIDE an already-authenticated, RBAC-gated (`staff:register`) admin/
reception request -- `composition_root.build_provision_staff_identity`
therefore wires THIS class against `open_runtime_connection()` (RLS-scoped,
`app.*` GUCs already set) for that one caller, never `app.db.engine`, per
task 10.2's own general instruction ("never `app.db.engine` for a
request-scoped business query"). `user_credentials`' own RLS policy
(`user_credentials_tenant`) is satisfied trivially since the caller's own
`app.tenant_id` GUC already matches the tenant being provisioned into;
`users` DOES carry a real RLS write policy (`users_admin_write`, migration
613f9ea3526f: `ENABLE`+`FORCE ROW LEVEL SECURITY` plus a predicate requiring
`current_setting('app.role') = 'admin'` literally) -- this is exactly WHY
`role_scope.py`'s `scoped_as_admin` exists at all (composition root's
`AdminElevatedUserDirectory` wraps THIS method with it). **Doc fix, this
session:** an earlier revision of this paragraph incorrectly claimed "`users`
itself carries no RLS policy at all (migration 8fc0dc6f958d)" -- that
migration only creates the table; 613f9ea3526f is the one that adds RLS to
it. `role_scope.py`'s own `scoped_as_admin` docstring already had this right;
corrected here to match.

**Duplicate-email race (fix, CONFIRMED fresh-review finding, this session):**
`ProvisionStaffIdentity.execute`'s own `find_by_email` pre-check is a plain
read-then-write with no locking -- two concurrent registrations for the same
email can both pass it before either INSERT below runs. `user_credentials`'
real `UNIQUE (tenant_id, email)` constraint (migration 9f1c4a7b2e3d) is the
backstop, but only if the resulting `IntegrityError` is caught and
translated -- `provision_staff_user` now does, mirroring the EXACT
catch-and-translate convention `PostgresSchedulingRepository
.create_appointment`/`PostgresShiftRepository.create_shift` already
establish for their own EXCLUDE-constraint races (`begin_nested()` +
`except IntegrityError`)."""

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
        # Two INSERTs, same connection/transaction (caller's already-open
        # runtime connection -- see this module's own docstring for why
        # THIS method, unlike every other one here, is wired against
        # `open_runtime_connection()`), not a single data-modifying CTE
        # (unlike `link_auth_subject` above): `users.id` is a
        # `gen_random_uuid()` PK that `user_credentials.user_id` needs to
        # reference, and there is no single-statement way to INSERT into
        # both tables while satisfying `user_credentials`' composite FK
        # `FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id,
        # id)` without first knowing the generated id.
        #
        # Both INSERTs share ONE `begin_nested()` SAVEPOINT (fix, CONFIRMED
        # fresh-review finding -- see this module's own docstring): the
        # `user_credentials` INSERT can hit a genuine unique-email race even
        # when `ProvisionStaffIdentity.execute`'s own `find_by_email`
        # pre-check passed, and without a SAVEPOINT here Postgres would mark
        # the WHOLE transaction aborted, breaking every later statement on
        # this connection -- and, since only the SECOND insert would be
        # rolled back on its own, leave an orphaned `users` row with no
        # matching `user_credentials` behind. Wrapping BOTH inserts in the
        # SAME `begin_nested()` means a failure on either one rolls back
        # both cleanly, same "catch the ONE constraint an authorized,
        # well-formed write can realistically hit" convention
        # `PostgresSchedulingRepository.create_appointment`/
        # `PostgresShiftRepository.create_shift` already establish.
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
        assert account is not None  # just inserted, on the same connection/transaction
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
