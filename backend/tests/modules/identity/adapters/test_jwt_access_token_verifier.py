from datetime import timedelta

from app.modules.identity.adapters.outbound.tokens.jwt_access_token_issuer import JwtAccessTokenIssuer
from app.modules.identity.adapters.outbound.tokens.jwt_access_token_verifier import JwtAccessTokenVerifier
from app.shared_kernel.clock import SystemClock
from app.shared_kernel.tenant_context import TenantContext

_SECRET = "test-only-signing-secret"


async def test_verifies_a_token_issued_by_the_matching_issuer() -> None:
    issuer = JwtAccessTokenIssuer(secret=_SECRET, clock=SystemClock())
    ctx = TenantContext(tenant_id="t1", role="reception", site_id="s1", actor_id="u1")
    token = await issuer.issue(ctx, ttl=timedelta(minutes=10))

    verifier = JwtAccessTokenVerifier(secret=_SECRET)
    claims = verifier.verify(token)

    assert claims is not None
    assert claims.sub == "u1"
    assert claims.tenant_id == "t1"
    assert claims.site_id == "s1"
    assert claims.role == "reception"


async def test_returns_none_for_a_token_signed_with_a_different_secret() -> None:
    issuer = JwtAccessTokenIssuer(secret=_SECRET, clock=SystemClock())
    ctx = TenantContext(tenant_id="t1", role="admin")
    token = await issuer.issue(ctx, ttl=timedelta(minutes=10))

    verifier = JwtAccessTokenVerifier(secret="wrong-secret")
    assert verifier.verify(token) is None


async def test_returns_none_for_an_expired_token() -> None:
    # Negative ttl -- guaranteed expired regardless of when the suite runs.
    issuer = JwtAccessTokenIssuer(secret=_SECRET, clock=SystemClock())
    ctx = TenantContext(tenant_id="t1", role="admin")
    token = await issuer.issue(ctx, ttl=timedelta(minutes=-10))

    verifier = JwtAccessTokenVerifier(secret=_SECRET)
    assert verifier.verify(token) is None


async def test_returns_none_for_a_malformed_token() -> None:
    verifier = JwtAccessTokenVerifier(secret=_SECRET)
    assert verifier.verify("not-a-jwt-at-all") is None


async def test_verifies_an_anonymous_token_without_a_sub_claim() -> None:
    issuer = JwtAccessTokenIssuer(secret=_SECRET, clock=SystemClock())
    ctx = TenantContext(tenant_id="t1", role="patient", site_id=None, actor_id=None)
    token = await issuer.issue(ctx, ttl=timedelta(minutes=10))

    verifier = JwtAccessTokenVerifier(secret=_SECRET)
    claims = verifier.verify(token)

    assert claims is not None
    assert claims.sub is None
    assert claims.tenant_id == "t1"
