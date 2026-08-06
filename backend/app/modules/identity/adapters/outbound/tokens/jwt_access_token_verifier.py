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
            # Any verification failure -> reject/refresh; do not surface subtype.
            return None

        return AccessTokenClaims(
            sub=claims.get("sub"),
            tenant_id=claims.get("tenant_id"),
            site_id=claims.get("site_id"),
            role=claims.get("role"),
        )
