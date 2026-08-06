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
