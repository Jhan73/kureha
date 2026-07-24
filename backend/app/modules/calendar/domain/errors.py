"""Calendar-module error hierarchy, subclassing `shared_kernel.errors` the
same way every other module does -- never a bare `DomainError` (design.md
§2.5)."""

from app.shared_kernel.errors import NotFoundError, ValidationError


class CalendarCredentialNotFoundError(NotFoundError):
    """No `calendar_credentials` row (or none still active/non-revoked)
    matches the given `(tenant_id, patient_id)` pair."""


class OAuthStateMismatchError(ValidationError):
    """The OAuth2 `state` parameter received on the callback does not match
    the one generated when the flow started (design.md §7.3's anti-CSRF
    check). The request MUST be rejected -- never proceed to exchange
    `code` for tokens when this is raised.

    Subclasses `ValidationError`, not `NotAuthorizedError`: design.md §7.3
    requires a 400 response, and §21.1's category table only allows 400
    under the `validation` category (`auth` is 401/403-only) -- this is a
    malformed/stale request parameter, not an RBAC/RLS permission denial."""


class CalendarOAuthExchangeError(ValidationError):
    """Google's `/token` endpoint rejected the authorization `code`
    presented on the OAuth2 callback (expired, already consumed, wrong
    `redirect_uri`, ...) -- added task 10.1 (routers), the first call site
    that actually exchanges a `code` for tokens. Surfaced as a client-side
    validation failure (422 via `platform/inbound/api/errors.py`'s
    `ValidationError` mapping), not an internal error: a stale/reused `code`
    reflects the caller's redirect, not this service's own fault."""
