"""`AccessTokenVerifierPort` (design.md §4.2/§17.4, tasks.md task 5.1): the
counterpart to `AccessTokenIssuerPort` -- decodes and verifies the access JWT
`JwtAccessTokenIssuer` mints. Consumed by the platform-layer access-control
middleware (`app/platform/inbound/api/access_control/middleware.py`), which
needs the raw decoded claims (not yet a trusted `TenantContext` -- design.md
§4.2 is explicit that authorization claims are re-resolved from the live
`users` row, never trusted verbatim from the token). Kept behind a port for
the same reason `AccessTokenIssuerPort` is: unit tests can supply a fake
without decoding a real JWT."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    """Raw decoded claims from a Kureha access JWT (design.md §17.4's claim
    set: `sub`/`tenant_id`/`site_id`/`role`). Deliberately NOT a
    `TenantContext` -- these claims are untrusted for authorization purposes
    until re-resolved against the live `users` row (design.md §4.2:
    "el claim de rol viaja en el token solo como pista")."""

    sub: str | None
    tenant_id: str | None
    site_id: str | None
    role: str | None


class AccessTokenVerifierPort(Protocol):
    def verify(self, token: str) -> AccessTokenClaims | None:
        """Returns the decoded claims if `token` has a valid signature and
        is not expired, or `None` for ANY verification failure (bad
        signature, expired, malformed) -- callers only ever need the single
        "reject, require refresh" branch (design.md §4.2), never the exact
        failure reason."""
        ...
