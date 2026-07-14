"""`Login` use case (design.md §17.3/§17.4, tasks.md task 4.3): resolves an
`AuthnResult` (authn-only) to exactly one `users` row and mints a fresh
access+refresh pair. Two entry points, `with_password`/`with_google`,
because the federated flow has extra branches (existing-linked-account,
account-link-required, first-time-provisioning) the password flow never
hits (design.md §17.3).

**`default_site_id` (federated, first-time-signup branch only):** deciding
WHICH site a self-registering patient belongs to is a Tenancy/Scheduling
policy question (tasks.md Phase 6/7 -- neither module exists yet). This use
case does not invent that policy; it accepts an already-resolved
`default_site_id` from its caller. Until a future phase's composition root
supplies one, a first-time Google sign-in with no existing `users` match is
correctly denied+audited via `UnmappedIdentityError` -- spec
`user-authentication`'s "Unmapped identity is denied" scenario is satisfied
either way; only the "First-time Google sign-in creates an account" scenario
is gated on a caller providing `default_site_id`.
"""

from datetime import timedelta

from app.modules.governance.audit.application.ports.driven.audit_log import AuditLogPort
from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.modules.identity.application.ports.driven.auth import AuthPort
from app.modules.identity.application.ports.driven.secret_generator import SecretGeneratorPort
from app.modules.identity.application.ports.driven.session_store import SessionStorePort
from app.modules.identity.application.ports.driven.token_issuer import AccessTokenIssuerPort
from app.modules.identity.application.ports.driven.user_directory import UserDirectoryPort
from app.modules.identity.application.token_minting import mint_login_result
from app.modules.identity.domain.errors import InactiveUserError, UnmappedIdentityError
from app.modules.identity.domain.login_result import AccountLinkRequired, LoginResult
from app.modules.identity.domain.user_account import UserAccount
from app.shared_kernel.clock import ClockPort

_DEFAULT_ACCESS_TTL = timedelta(minutes=10)
_DEFAULT_REFRESH_TTL = timedelta(days=30)


class Login:
    def __init__(
        self,
        auth: AuthPort,
        user_directory: UserDirectoryPort,
        session_store: SessionStorePort,
        token_issuer: AccessTokenIssuerPort,
        secret_generator: SecretGeneratorPort,
        audit_log: AuditLogPort,
        clock: ClockPort,
        *,
        access_token_ttl: timedelta = _DEFAULT_ACCESS_TTL,
        refresh_token_ttl: timedelta = _DEFAULT_REFRESH_TTL,
    ) -> None:
        """`user_directory`/`session_store` need the SAME elevated,
        pre-auth `app.db.engine` connection privilege documented on
        `UserDirectoryPort`/`SessionStorePort` (no `app.*` GUC exists yet
        when `Login` runs -- nothing to look up a `TenantContext` from).

        `audit_log` has the SAME constraint, for the SAME reason, even
        though `PostgresAuditLog`'s own docstring (adapters/outbound/
        postgres/audit_log.py) generally requires `app.db.runtime_engine`
        (RLS-scoped, GUCs already set) -- that general contract is
        impossible to satisfy here, since `Login` writes its unmapped-
        identity audit entry BEFORE any GUC can exist. `PostgresAuditLog`'s
        constructor only takes a generic `AsyncConnection` (no engine
        binding baked into the class itself), so it CAN be constructed
        against an elevated `app.db.engine` connection instead -- the
        composition root (Phase 10) MUST wire THIS caller's `audit_log`
        that way, as a narrow exception to `PostgresAuditLog`'s general
        `runtime_engine` contract, mirroring the same exception already
        documented for `user_directory`/`session_store`."""
        self._auth = auth
        self._user_directory = user_directory
        self._session_store = session_store
        self._token_issuer = token_issuer
        self._secret_generator = secret_generator
        self._audit_log = audit_log
        self._clock = clock
        self._access_token_ttl = access_token_ttl
        self._refresh_token_ttl = refresh_token_ttl

    async def with_password(self, tenant_id: str, *, email: str, password: str) -> LoginResult:
        authn = await self._auth.verify_password(email, password)
        user = await self._user_directory.find_by_email(tenant_id, authn.email)
        if user is None:
            await self._deny_unmapped(
                tenant_id,
                email=authn.email,
                subject=authn.subject,
                reason="authenticated identity has no resolvable users row",
            )
            raise UnmappedIdentityError()
        if not user.is_active:
            raise InactiveUserError()
        return await self._issue(tenant_id, user)

    async def with_google(
        self, tenant_id: str, *, id_token: str, default_site_id: str | None = None
    ) -> LoginResult | AccountLinkRequired:
        authn = await self._auth.verify_federated("google", id_token)

        linked_user = await self._user_directory.find_by_auth_subject(tenant_id, authn.subject)
        if linked_user is not None:
            if not linked_user.is_active:
                raise InactiveUserError()
            return await self._issue(tenant_id, linked_user)

        existing = await self._user_directory.find_by_email(tenant_id, authn.email)
        if existing is not None:
            if existing.is_linked_to_federated_provider:
                # Email already linked to a DIFFERENT federated subject than
                # the one just presented -- a genuine conflict, not a normal
                # "link my password account" flow. Safe default: deny+audit,
                # same as any other unmapped-identity case, rather than
                # silently relinking.
                await self._deny_unmapped(
                    tenant_id,
                    email=authn.email,
                    subject=authn.subject,
                    reason="email already linked to a different federated subject",
                )
                raise UnmappedIdentityError()
            return AccountLinkRequired(
                existing_user_id=existing.id,
                email=authn.email,
                pending_subject=authn.subject,
                email_verified=authn.email_verified,
            )

        if default_site_id is None:
            await self._deny_unmapped(
                tenant_id,
                email=authn.email,
                subject=authn.subject,
                reason="first-time federated sign-in with no default_site_id available for provisioning",
            )
            raise UnmappedIdentityError()

        provisioned = await self._user_directory.provision_patient_user(
            tenant_id,
            site_id=default_site_id,
            email=authn.email,
            auth_subject=authn.subject,
            email_verified=authn.email_verified,
        )
        return await self._issue(tenant_id, provisioned)

    async def _issue(self, tenant_id: str, user: UserAccount) -> LoginResult:
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

    async def _deny_unmapped(self, tenant_id: str, *, email: str, subject: str, reason: str) -> None:
        # `_deny_unmapped` is called from 3 distinct scenarios (no `users`
        # row at all; Google email linked to a DIFFERENT subject -- conflict;
        # first-time Google sign-in missing `default_site_id`) that all
        # write the same `AuditAction`. Carrying the attempted email/subject
        # in `payload` (and a scenario-specific `reason`) keeps enough
        # forensic detail to tell them apart later without adding a new
        # `AuditAction` per scenario (fix, confirmed review finding).
        await self._audit_log.record(
            AuditEntry(
                tenant_id=tenant_id,
                actor_type=AuditActorType.SYSTEM,
                action=AuditAction.AUTH_UNMAPPED_IDENTITY,
                object_type="user",
                reason=reason,
                payload={"email": email, "subject": subject},
            )
        )
