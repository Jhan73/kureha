"""`AccessTokenIssuerPort` (design.md §17.4/ADR-15): mints Kureha's own
short-lived, stateless access JWT. Implemented in MVP by
`JwtAccessTokenIssuer` (adapters/outbound/tokens/jwt_access_token_issuer.py).
Kept behind a port (rather than calling `pyjwt` directly from the use case)
so `Login`/`RefreshToken` unit tests can assert on the `TenantContext`/`ttl`
passed in without decoding a real JWT."""

from datetime import timedelta
from typing import Protocol

from app.shared_kernel.tenant_context import TenantContext


class AccessTokenIssuerPort(Protocol):
    async def issue(self, ctx: TenantContext, *, ttl: timedelta) -> str:
        """Returns a signed access token encoding `ctx`'s claims
        (`tenant_id`/`site_id`/`role`/`actor_id`) and an expiry `ttl` from
        now (design.md §17.4: "~10 min"). Never persisted -- stateless."""
        ...
