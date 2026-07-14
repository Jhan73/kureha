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
