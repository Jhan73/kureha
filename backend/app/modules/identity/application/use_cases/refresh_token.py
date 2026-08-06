from datetime import timedelta

from app.modules.identity.application.ports.driven.rotation_replay_cache import RotationReplayCachePort
from app.modules.identity.application.ports.driven.secret_generator import SecretGeneratorPort
from app.modules.identity.application.ports.driven.session_store import SessionStorePort
from app.modules.identity.application.ports.driven.token_issuer import AccessTokenIssuerPort
from app.modules.identity.application.ports.driven.user_directory import UserDirectoryPort
from app.modules.identity.domain.errors import (
    InactiveUserError,
    InvalidRefreshTokenError,
    RefreshReuseDetectedError,
)
from app.modules.identity.domain.login_result import LoginResult
from app.modules.identity.domain.refresh_session import RefreshSession
from app.modules.identity.domain.refresh_token_hash import hash_refresh_token
from app.modules.identity.domain.session_policy import SessionPolicy
from app.modules.identity.domain.user_account import UserAccount
from app.shared_kernel.clock import ClockPort
from app.shared_kernel.tenant_context import TenantContext

_DEFAULT_ACCESS_TTL = timedelta(minutes=10)
_DEFAULT_REFRESH_TTL = timedelta(days=30)
_DEFAULT_GRACE_PERIOD = timedelta(seconds=30)


class RefreshToken:
    def __init__(
        self,
        session_store: SessionStorePort,
        user_directory: UserDirectoryPort,
        token_issuer: AccessTokenIssuerPort,
        secret_generator: SecretGeneratorPort,
        replay_cache: RotationReplayCachePort,
        clock: ClockPort,
        *,
        access_token_ttl: timedelta = _DEFAULT_ACCESS_TTL,
        refresh_token_ttl: timedelta = _DEFAULT_REFRESH_TTL,
        grace_period: timedelta = _DEFAULT_GRACE_PERIOD,
    ) -> None:
        self._session_store = session_store
        self._user_directory = user_directory
        self._token_issuer = token_issuer
        self._secret_generator = secret_generator
        self._replay_cache = replay_cache
        self._clock = clock
        self._access_token_ttl = access_token_ttl
        self._refresh_token_ttl = refresh_token_ttl
        self._grace_period = grace_period

    async def execute(self, *, refresh_token: str) -> LoginResult:
        presented_hash = hash_refresh_token(refresh_token)
        session = await self._session_store.find_by_hash(presented_hash)
        if session is None:
            raise InvalidRefreshTokenError()

        now = self._clock.now()

        if session.is_revoked:
            return await self._handle_already_rotated(session, now, presented_refresh_token=refresh_token)

        if SessionPolicy.is_expired(session, now=now):
            raise InvalidRefreshTokenError()

        return await self._rotate(session, now)

    async def _handle_already_rotated(self, session: RefreshSession, now, *, presented_refresh_token: str) -> LoginResult:
        # `RefreshSession` has no revocation-cause field -- `revoked_at`
        # Successor proves rotation (vs logout/admin-revoke); required before grace.
        successor = await self._session_store.find_successor(session.id)
        if successor is None:
            # Not a rotation replay at all -- an ordinary revoked refresh
            # token (logged out, admin-revoked, or the terminal node of an
            # earlier chain-revoke). NOT a theft signal on its own: escalating
            # this to a full chain-revoke would incorrectly punish a
            # logged-out user retrying their own old token.
            raise InvalidRefreshTokenError()

        if not SessionPolicy.is_within_rotation_grace_period(session, now=now, grace_period=self._grace_period):
            # Rotation successor exists but replay is past grace -> reuse attack.
            await self._session_store.revoke_chain(session.id, revoked_at=now)
            raise RefreshReuseDetectedError()

        cached = self._replay_cache.get(session.refresh_token_hash)
        if cached is not None:
            access_token, new_refresh_token = cached
            user = await self._require_active_user(session)
            return LoginResult(access_token=access_token, refresh_token=new_refresh_token, user=user)

        # Cache miss (e.g. a different instance handled the original
        # rotation, see RotationReplayCachePort's docstring). The successor
        # session already exists, but only its HASH was ever persisted --
        # the plaintext refresh token minted for it is not recoverable here.
        # Minting a SECOND rotation from the same old (already-revoked)
        # session would create a sibling successor of the same parent, which
        # breaks the single-chain invariant `revoke_chain` relies on. So
        # instead: mint a fresh ACCESS TOKEN only, scoped to the ONE TRUE
        # successor found above, without creating another refresh-session
        # row or rotating again. The caller's presented (still
        # grace-period-valid) refresh token is echoed back unchanged --
        # idempotent retries within the grace window keep converging on the
        # same successor; the caller's actual new refresh token is whatever
        # the original rotation response already returned (delivered via a
        # cache hit on another instance, or recoverable from that first
        # response if this call is a concurrent duplicate, not a lost-reply
        # retry).
        user = await self._require_active_user(successor)
        ctx = TenantContext(tenant_id=successor.tenant_id, role=user.role, site_id=user.site_id, actor_id=user.id)
        access_token = await self._token_issuer.issue(ctx, ttl=self._access_token_ttl)
        return LoginResult(access_token=access_token, refresh_token=presented_refresh_token, user=user)

    async def _rotate(self, session: RefreshSession, now) -> LoginResult:
        user = await self._require_active_user(session)

        ctx = TenantContext(tenant_id=session.tenant_id, role=user.role, site_id=user.site_id, actor_id=user.id)
        access_token = await self._token_issuer.issue(ctx, ttl=self._access_token_ttl)
        new_refresh_token = self._secret_generator.generate()
        new_hash = hash_refresh_token(new_refresh_token)

        await self._session_store.rotate(
            session.id,
            session.tenant_id,
            session.user_id,
            refresh_token_hash=new_hash,
            expires_at=now + self._refresh_token_ttl,
            revoked_at=now,
        )
        self._replay_cache.set(session.refresh_token_hash, access_token=access_token, refresh_token=new_refresh_token)

        return LoginResult(access_token=access_token, refresh_token=new_refresh_token, user=user)

    async def _require_active_user(self, session: RefreshSession) -> UserAccount:
        user = await self._user_directory.get_by_id(session.tenant_id, session.user_id)
        if user is None or not user.is_active:
            raise InactiveUserError()
        return user
