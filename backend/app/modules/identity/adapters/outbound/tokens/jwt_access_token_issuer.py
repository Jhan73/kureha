from datetime import timedelta

import jwt

from app.modules.identity.adapters.outbound.tokens.jwt_constants import DEFAULT_ALGORITHM
from app.shared_kernel.clock import ClockPort
from app.shared_kernel.tenant_context import TenantContext


class JwtAccessTokenIssuer:
    def __init__(self, *, secret: str, clock: ClockPort, algorithm: str = DEFAULT_ALGORITHM) -> None:
        self._secret = secret
        self._clock = clock
        self._algorithm = algorithm

    async def issue(self, ctx: TenantContext, *, ttl: timedelta) -> str:
        now = self._clock.now()
        claims = {
            "tenant_id": ctx.tenant_id,
            "site_id": ctx.site_id,
            "role": ctx.role,
            "iat": now,
            "exp": now + ttl,
        }
        # PyJWT rejects a non-string "sub" claim outright (raises
        # InvalidSubjectError on decode) -- omit it entirely for an
        # anonymous/system TenantContext (actor_id=None) rather than
        # encoding a `None` that would fail on the very next decode.
        if ctx.actor_id is not None:
            claims["sub"] = ctx.actor_id
        return jwt.encode(claims, self._secret, algorithm=self._algorithm)
