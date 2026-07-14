"""Task 4.1/4.3: `JwtAccessTokenIssuer` -- production `AccessTokenIssuerPort`
impl. Kureha mints its own access JWT (design.md §17.4/ADR-15), signed
HS256 with a shared secret (no external IdP round trip per request)."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.modules.identity.adapters.outbound.tokens.jwt_access_token_issuer import JwtAccessTokenIssuer
from app.shared_kernel.tenant_context import TenantContext

_SECRET = "test-only-signing-secret"


class _FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


@pytest.mark.asyncio
async def test_issued_token_decodes_with_the_expected_claims() -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    issuer = JwtAccessTokenIssuer(secret=_SECRET, clock=_FixedClock(now))
    ctx = TenantContext(tenant_id="t1", role="reception", site_id="s1", actor_id="u1")

    token = await issuer.issue(ctx, ttl=timedelta(minutes=10))

    claims = jwt.decode(token, _SECRET, algorithms=["HS256"], options={"verify_exp": False})
    assert claims["tenant_id"] == "t1"
    assert claims["site_id"] == "s1"
    assert claims["role"] == "reception"
    assert claims["sub"] == "u1"
    assert claims["exp"] == int((now + timedelta(minutes=10)).timestamp())
    assert claims["iat"] == int(now.timestamp())


@pytest.mark.asyncio
async def test_token_signed_with_a_different_secret_fails_verification() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    issuer = JwtAccessTokenIssuer(secret=_SECRET, clock=_FixedClock(now))
    ctx = TenantContext(tenant_id="t1", role="admin")

    token = await issuer.issue(ctx, ttl=timedelta(minutes=10))

    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(token, "wrong-secret", algorithms=["HS256"])


@pytest.mark.asyncio
async def test_anonymous_context_omits_actor_id_claim_gracefully() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    issuer = JwtAccessTokenIssuer(secret=_SECRET, clock=_FixedClock(now))
    ctx = TenantContext(tenant_id="t1", role="patient", site_id=None, actor_id=None)

    token = await issuer.issue(ctx, ttl=timedelta(minutes=10))
    claims = jwt.decode(token, _SECRET, algorithms=["HS256"], options={"verify_exp": False})

    assert "sub" not in claims
    assert claims["site_id"] is None
