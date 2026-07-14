"""`RefreshToken` use case (design.md §17.4, ADR-15, tasks.md task 4.4):
validates an opaque refresh token against `user_sessions`, re-checks live
`active` status, re-resolves the current role, rotates the refresh, and
mints a fresh access token. Implements the 30s rotation grace period and
reuse-detection chain-revoke described in design.md §17.4.

Deliberately does NOT accept a `TenantContext` -- refreshing is, like
`Login`, a pre-session operation: the caller presents only the opaque
refresh token, and `tenant_id`/`user_id` are recovered from whichever
`user_sessions` row it hashes to (see `SessionStorePort.find_by_hash`'s
docstring for why this is a global, not tenant-scoped, lookup).

**Grace period only applies to a genuine rotation replay** (security fix):
`RefreshSession` has no revocation-cause field, so `_handle_already_rotated`
uses `SessionStorePort.find_successor` to tell "revoked by rotation" (a
successor row exists) apart from any other revocation cause -- logout,
admin-revoke, or the terminal node of an earlier chain-revoke (no
successor). A revoked token with no successor is always an ordinary
`InvalidRefreshTokenError`, never grace-period leniency and never escalated
to a reuse-attack chain-revoke."""

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
        # alone cannot tell "revoked by rotation" apart from "revoked by
        # logout/admin-revoke". A successor row (`rotated_from == this
        # session's id`) only exists when a rotation genuinely happened, so
        # it is the source of truth here (security fix, design.md §17.4).
        successor = await self._session_store.find_successor(session.id)
        if successor is None:
            # Not a rotation replay at all -- an ordinary revoked refresh
            # token (logged out, admin-revoked, or the terminal node of an
            # earlier chain-revoke). NOT a theft signal on its own: escalating
            # this to a full chain-revoke would incorrectly punish a
            # logged-out user retrying their own old token.
            raise InvalidRefreshTokenError()

        if not SessionPolicy.is_within_rotation_grace_period(session, now=now, grace_period=self._grace_period):
            # A genuine rotation successor exists AND the old token is being
            # replayed past the grace window -- the actual reuse-attack
            # signal (design.md §17.4).
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
