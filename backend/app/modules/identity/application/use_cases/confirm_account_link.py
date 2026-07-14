"""`ConfirmAccountLink` use case (design.md §17.3, tasks.md task 4.6, spec
`user-authentication` -> "Email Verification for Account Linking"): links a
federated (Google) subject to an existing password-based `users` row.

**Caller contract:** this use case performs the link unconditionally once
called -- it does NOT itself re-verify the user's identity/consent to link.
The confirmation step (spec: "the system MUST require explicit confirmation
before linking") is a UX/endpoint concern (e.g. re-entering the existing
account's password, or clicking a confirmation link) that belongs to a
future Phase 10 endpoint, not this use case. `Login.with_google` is what
detects the "needs confirmation" state and returns `AccountLinkRequired`
(never auto-calling this) -- see that method's docstring."""

from datetime import timedelta

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


class ConfirmAccountLink:
    def __init__(
        self,
        user_directory: UserDirectoryPort,
        session_store: SessionStorePort,
        token_issuer: AccessTokenIssuerPort,
        secret_generator: SecretGeneratorPort,
        clock: ClockPort,
        *,
        access_token_ttl: timedelta = _DEFAULT_ACCESS_TTL,
        refresh_token_ttl: timedelta = _DEFAULT_REFRESH_TTL,
    ) -> None:
        self._user_directory = user_directory
        self._session_store = session_store
        self._token_issuer = token_issuer
        self._secret_generator = secret_generator
        self._clock = clock
        self._access_token_ttl = access_token_ttl
        self._refresh_token_ttl = refresh_token_ttl

    async def execute(self, tenant_id: str, *, user_id: str, auth_subject: str, email_verified: bool) -> LoginResult:
        user = await self._user_directory.get_by_id(tenant_id, user_id)
        if user is None:
            raise UnmappedIdentityError()
        if not user.is_active:
            # Same live-status gate `Login.with_password`/`with_google` both
            # apply before minting (fix, confirmed review finding): a
            # deactivated account must not be able to complete account
            # linking and walk away with a fresh token pair.
            raise InactiveUserError()

        linked_user = await self._user_directory.link_auth_subject(
            tenant_id, user_id, auth_subject=auth_subject, email_verified=email_verified
        )
        return await mint_login_result(
            tenant_id,
            linked_user,
            token_issuer=self._token_issuer,
            secret_generator=self._secret_generator,
            session_store=self._session_store,
            now=self._clock.now(),
            access_token_ttl=self._access_token_ttl,
            refresh_token_ttl=self._refresh_token_ttl,
        )
