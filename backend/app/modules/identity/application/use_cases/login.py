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
        """Pre-auth: user_directory, session_store, and audit_log need elevated connections (no GUCs yet)."""
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
