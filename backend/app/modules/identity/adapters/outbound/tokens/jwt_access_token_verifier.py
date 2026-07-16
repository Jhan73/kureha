"""`JwtAccessTokenVerifier`: production `AccessTokenVerifierPort` impl,
counterpart to `JwtAccessTokenIssuer` (design.md §17.4/ADR-15, tasks.md task
5.1). Same HS256 secret/algorithm -- the access-control middleware verifies
exactly the tokens `Login`/`RefreshToken` mint."""

import jwt

from app.modules.identity.adapters.outbound.tokens.jwt_constants import DEFAULT_ALGORITHM
from app.modules.identity.application.ports.driven.token_verifier import AccessTokenClaims


class JwtAccessTokenVerifier:
    def __init__(self, *, secret: str, algorithm: str = DEFAULT_ALGORITHM) -> None:
        self._secret = secret
        self._algorithm = algorithm

    def verify(self, token: str) -> AccessTokenClaims | None:
        try:
            claims = jwt.decode(token, self._secret, algorithms=[self._algorithm])
        except jwt.PyJWTError:
            # Bad signature, expired, malformed -- design.md §4.2 treats every
            # verification failure as the same "reject, refresh required"
            # branch, so the specific `PyJWTError` subtype is deliberately
            # not surfaced to the caller.
            return None

        return AccessTokenClaims(
            sub=claims.get("sub"),
            tenant_id=claims.get("tenant_id"),
            site_id=claims.get("site_id"),
            role=claims.get("role"),
        )
