"""Shared token-minting helper for `Login` and `ConfirmAccountLink` -- both
end with the identical "mint access + opaque refresh, persist the refresh
hash" sequence (design.md §17.4). `RefreshToken` does NOT use this: its
rotation flow revokes the old session as part of the same step, which this
helper does not (and should not) know about."""

from datetime import datetime, timedelta

from app.modules.identity.application.ports.driven.secret_generator import SecretGeneratorPort
from app.modules.identity.application.ports.driven.session_store import SessionStorePort
from app.modules.identity.application.ports.driven.token_issuer import AccessTokenIssuerPort
from app.modules.identity.domain.login_result import LoginResult
from app.modules.identity.domain.refresh_token_hash import hash_refresh_token
from app.modules.identity.domain.user_account import UserAccount
from app.shared_kernel.tenant_context import TenantContext


async def mint_login_result(
    tenant_id: str,
    user: UserAccount,
    *,
    token_issuer: AccessTokenIssuerPort,
    secret_generator: SecretGeneratorPort,
    session_store: SessionStorePort,
    now: datetime,
    access_token_ttl: timedelta,
    refresh_token_ttl: timedelta,
) -> LoginResult:
    ctx = TenantContext(tenant_id=tenant_id, role=user.role, site_id=user.site_id, actor_id=user.id)
    access_token = await token_issuer.issue(ctx, ttl=access_token_ttl)
    refresh_token = secret_generator.generate()
    await session_store.create(
        tenant_id,
        user.id,
        refresh_token_hash=hash_refresh_token(refresh_token),
        expires_at=now + refresh_token_ttl,
    )
    return LoginResult(access_token=access_token, refresh_token=refresh_token, user=user)
