"""`UserDirectoryPort` (design.md §17.3): the pre-auth resolution port
`Login`/`RefreshToken`/`ConfirmAccountLink` depend on to map an IdP identity
(email/subject) to exactly one `users` row, and back.

**Elevated-connection contract, NOT the `runtime_engine`/RLS pattern every
other Phase 3 postgres adapter follows.** Resolving `subject`/`email` -> a
`users` row necessarily happens BEFORE any `app.*` GUC (`app.tenant_id`,
`app.user_id`, `app.role`, ...) can be set -- that is exactly the
"chicken-and-egg" problem PR 3's review flagged on the `users` RLS policies
(613f9ea3526f, point 3) as "Phase 4/5 architecture, out of scope [of PR 3]".
`PostgresUserDirectory` (adapters/outbound/postgres/user_directory.py) is
wired, by the composition root, against `app.db.engine` (the elevated,
RLS-bypassing role already used for Alembic/DDL -- see that module's
docstring) rather than `app.db.runtime_engine`. This is a deliberate,
narrow exception to "never use `app.db.engine` for a business query"
(task 10.2's own instruction): the identity module's pre-auth resolution is
the one path in the system that legitimately runs before any tenant
session context exists, so there is no `app_runtime` GUC context to set in
the first place."""

from typing import Protocol

from app.modules.identity.domain.user_account import UserAccount


class UserDirectoryPort(Protocol):
    async def find_by_email(self, tenant_id: str, email: str) -> UserAccount | None: ...

    async def find_by_auth_subject(self, tenant_id: str, auth_subject: str) -> UserAccount | None: ...

    async def get_by_id(self, tenant_id: str, user_id: str) -> UserAccount | None:
        """Live re-fetch, used by `RefreshToken` to re-check `status` and
        re-resolve `role` on every refresh (design.md §17.4)."""
        ...

    async def link_auth_subject(
        self, tenant_id: str, user_id: str, *, auth_subject: str, email_verified: bool
    ) -> UserAccount:
        """Links a federated subject to an existing `users` row -- either
        the fast path (first-time Google sign-in, subject not seen before,
        no existing account to confuse it with) or after `ConfirmAccountLink`
        has explicitly confirmed linking to a pre-existing password account
        (spec `user-authentication` -> "Email Verification for Account
        Linking": never silent). Raises `UnmappedIdentityError` if `user_id`
        has no matching `user_credentials` row."""
        ...

    async def provision_patient_user(
        self, tenant_id: str, *, site_id: str, email: str, auth_subject: str, email_verified: bool
    ) -> UserAccount:
        """First-time Google sign-in with no matching `users` row at all
        (spec -> "First-time Google sign-in creates an account"). Requires
        an explicit `site_id` -- deciding WHICH site a self-registering
        patient belongs to is a Tenancy/Scheduling-module policy question
        (tasks.md Phase 6/7, not yet built), deliberately not answered by
        the identity module itself; see `Login`'s docstring for the caller
        contract this implies."""
        ...

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
        """Creates a NEW `users` row + `user_credentials` row for a
        newly-INVITED staff member (`ProvisionStaffIdentity`, staff-invite
        batch) -- the FIRST real, working `UserDirectoryPort` provisioning
        implementation in this codebase (`provision_patient_user` above
        remains deliberately unimplemented, see its own docstring; this
        method is a genuinely different, simpler case: no `patient_id`/DNI
        collection, role is caller-supplied not defaulted).

        `role` is a plain `str`, not `staff.domain.staff_member.
        OperationalRole` -- the identity module MUST NOT import from the
        `staff` business module (backend/AGENTS.md, import-linter's
        "Business modules do not import each other directly" contract); the
        caller (a platform-layer router, which MAY import both modules)
        passes `OperationalRole.value` instead. Callers MUST supply
        `professional_id` when `role == "professional"` --
        `users`' own CHECK constraint (migration 8fc0dc6f958d: `CHECK (role
        <> 'professional' OR professional_id IS NOT NULL)`) rejects the
        INSERT otherwise; `ProvisionStaffIdentity` validates this UP FRONT
        (a clean `ValidationError`) rather than letting a raw
        `IntegrityError` leak through as an unmapped 500.

        `tenant_id`/`site_id` are trusted as already-resolved (RBAC-gated,
        authenticated caller) -- unlike `provision_patient_user`'s pre-auth
        federated-signup context, this always runs INSIDE an authenticated
        admin/reception request. See `PostgresUserDirectory`'s own
        implementation docstring for the resulting, narrower connection
        contract this one method uses (unlike every other method on this
        port)."""
        ...
