from app.shared_kernel.errors import ConflictError, NotAuthorizedError, NotFoundError


class InvalidCredentialsError(NotAuthorizedError):
    """Auth verification failed; same type for any failure cause (anti-enumeration)."""


class UnmappedIdentityError(NotAuthorizedError):
    """Authn succeeded but no users row maps to that identity."""


class InactiveUserError(NotAuthorizedError):
    """Authn succeeded but the resolved user is not active."""


class InvalidRefreshTokenError(NotAuthorizedError):
    """Refresh token is missing, unknown, or expired."""


class RefreshReuseDetectedError(NotAuthorizedError):
    """A already-rotated refresh token was presented again past the grace period."""


class EmailAlreadyRegisteredError(ConflictError):
    """Email already has credentials in this tenant."""


class SessionNotFoundError(NotFoundError):
    """No session matches the given id for the calling actor."""
