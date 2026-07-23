"""Calendar-module error hierarchy, subclassing `shared_kernel.errors` the
same way every other module does -- never a bare `DomainError` (design.md
§2.5)."""

from app.shared_kernel.errors import NotAuthorizedError, NotFoundError


class CalendarCredentialNotFoundError(NotFoundError):
    """No `calendar_credentials` row (or none still active/non-revoked)
    matches the given `(tenant_id, patient_id)` pair."""


class OAuthStateMismatchError(NotAuthorizedError):
    """The OAuth2 `state` parameter received on the callback does not match
    the one generated when the flow started (design.md §7.3's anti-CSRF
    check). The request MUST be rejected -- never proceed to exchange
    `code` for tokens when this is raised."""
