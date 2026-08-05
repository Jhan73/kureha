"""`CompletePasswordReset` use case (design.md §17 extension, staff-invite /
password-reset batch): exchanges a Supabase recovery/invite access token for
setting a new password, resolves the resulting identity to a `users` row,
and mints a fresh access+refresh pair -- the SAME completion step for BOTH
the invite-acceptance ("set your password") flow and the "forgot password"
flow (see `AuthPort.complete_password_reset`'s own docstring for why these
share one endpoint/use case rather than two).

**Judgment call, flagged not silently decided (per this batch's own
instructions):** mints tokens and logs the user in directly, rather than
just confirming success and requiring a separate login. Chosen for the best
UX on the invite-acceptance path in particular -- "I just set my password,
now I'm in" -- reusing `mint_login_result`/`Login`'s own issuance path
exactly (same helper, same TTLs), not a parallel one.

**Resolution order, mirrors `Login.with_google`'s existing-linked-account
fast path:** tries `find_by_auth_subject` FIRST (the invite-acceptance case
-- `ProvisionStaffIdentity` already stored `auth_subject` on
`user_credentials` at invite time, via the SAME Supabase subject
`complete_password_reset` returns here), falling back to `find_by_email`
(the "forgot password" case for an account that has no federated subject
linked at all, e.g. was never invited/never did a Google sign-in -- a
plain password-only account).

**`audit_log` is an `IsolatedAuditLogPort`, NOT a plain `AuditLogPort` (fix,
CONFIRMED fresh-review finding this batch):** `_deny_unmapped` used to write
through a plain `AuditLogPort` bound to the SAME connection `user_directory`/
`session_store` use. `tenant_id` here is caller-supplied and never validated
against a real `tenants` row (`PasswordResetConfirmRequest.tenant_id`, see
`routers/auth.py`'s own docstring), so a bogus value made the audit INSERT
itself violate `audit_logs`' real tenant FK -- and on that SHARED
connection, the resulting `IntegrityError` propagated straight through
`_deny_unmapped` uncaught (nothing here ever wrapped it), turning what should
have been a clean `UnmappedIdentityError`/401 into an unhandled 500. See
`IsolatedAuditLogPort`'s own docstring (governance/audit module) for the full
mechanism -- the fix is connection isolation, not just a try/except:
`record_audit_best_effort` alone is not sufficient once a SHARED transaction
is already poisoned."""

from datetime import timedelta

from app.modules.governance.audit.application.ports.driven.isolated_audit_log import IsolatedAuditLogPort
from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.modules.identity.application.ports.driven.auth import AuthPort
from app.modules.identity.application.ports.driven.secret_generator import SecretGeneratorPort
from app.modules.identity.application.ports.driven.session_store import SessionStorePort
from app.modules.identity.application.ports.driven.token_issuer import AccessTokenIssuerPort
from app.modules.identity.application.ports.driven.user_directory import UserDirectoryPort
from app.modules.identity.application.token_minting import mint_login_result
from app.modules.identity.domain.errors import InactiveUserError, UnmappedIdentityError
from app.modules.identity.domain.login_result import LoginResult
from app.shared_kernel.clock import ClockPort

_DEFAULT_ACCESS_TTL = timedelta(minutes=10)
_DEFAULT_REFRESH_TTL = timedelta(days=30)


class CompletePasswordReset:
    def __init__(
        self,
        auth: AuthPort,
        user_directory: UserDirectoryPort,
        session_store: SessionStorePort,
        token_issuer: AccessTokenIssuerPort,
        secret_generator: SecretGeneratorPort,
        audit_log: IsolatedAuditLogPort,
        clock: ClockPort,
        *,
        access_token_ttl: timedelta = _DEFAULT_ACCESS_TTL,
        refresh_token_ttl: timedelta = _DEFAULT_REFRESH_TTL,
    ) -> None:
        """Same elevated, pre-auth `app.db.engine` connection privilege
        contract as `Login`'s own constructor docstring: no `app.*` GUC/
        `TenantContext` exists yet when this use case runs (the caller has
        only a Supabase recovery token, not a Kureha session)."""
        self._auth = auth
        self._user_directory = user_directory
        self._session_store = session_store
        self._token_issuer = token_issuer
        self._secret_generator = secret_generator
        self._audit_log = audit_log
        self._clock = clock
        self._access_token_ttl = access_token_ttl
        self._refresh_token_ttl = refresh_token_ttl

    async def execute(self, tenant_id: str, *, recovery_token: str, new_password: str) -> LoginResult:
        authn = await self._auth.complete_password_reset(recovery_token, new_password)

        user = await self._user_directory.find_by_auth_subject(tenant_id, authn.subject)
        if user is None:
            user = await self._user_directory.find_by_email(tenant_id, authn.email)
        if user is None:
            await self._deny_unmapped(tenant_id, email=authn.email, subject=authn.subject)
            raise UnmappedIdentityError()
        if not user.is_active:
            raise InactiveUserError()

        return await mint_login_result(
            tenant_id,
            user,
            token_issuer=self._token_issuer,
            secret_generator=self._secret_generator,
            session_store=self._session_store,
            now=self._clock.now(),
            access_token_ttl=self._access_token_ttl,
            refresh_token_ttl=self._refresh_token_ttl,
        )

    async def _deny_unmapped(self, tenant_id: str, *, email: str, subject: str) -> None:
        # `record_best_effort`, not `record` -- see this module's own
        # docstring and `IsolatedAuditLogPort`'s docstring: this write runs
        # on its OWN, independent connection/transaction and NEVER raises,
        # so a bogus caller-supplied `tenant_id` FK-violating this INSERT
        # can never turn this clean deny into an unhandled 500.
        await self._audit_log.record_best_effort(
            AuditEntry(
                tenant_id=tenant_id,
                actor_type=AuditActorType.SYSTEM,
                action=AuditAction.AUTH_UNMAPPED_IDENTITY,
                object_type="user",
                reason="password reset completed but no users row maps to the resulting identity",
                payload={"email": email, "subject": subject},
            )
        )
