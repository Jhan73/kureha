"""Identity-module error hierarchy (design.md §17), subclassing
`shared_kernel.errors.NotAuthorizedError` the same way `rbac`'s
`ActionNotPermittedError` does -- authn/session failures are a form of "not
authorized", never surfaced as a generic 500."""

from app.shared_kernel.errors import NotAuthorizedError, NotFoundError


class InvalidCredentialsError(NotAuthorizedError):
    """Password or federated-token verification failed. Deliberately the
    SAME exception type regardless of cause (spec `user-authentication` ->
    "Wrong password rejected without enumeration": the caller must not be
    able to distinguish "wrong password" from "no such email")."""


class UnmappedIdentityError(NotAuthorizedError):
    """Authn succeeded (IdP proved who the caller is) but no `users` row
    maps to that identity (spec -> "Unmapped identity is denied"). Never
    resolved to a default role."""


class InactiveUserError(NotAuthorizedError):
    """Authn succeeded and a `users` row was resolved, but its live
    `status` is not `active` (spec `session-management` -> live enforcement
    of active status)."""


class InvalidRefreshTokenError(NotAuthorizedError):
    """The presented refresh token does not match any `user_sessions` row,
    or the matched row is expired (design.md §17.4)."""


class RefreshReuseDetectedError(NotAuthorizedError):
    """A refresh token already consumed by rotation was presented again,
    past the 30s grace period (design.md §17.4) -- a stolen-token signal.
    The entire rotation chain has already been revoked by the time this is
    raised."""


class SessionNotFoundError(NotFoundError):
    """`Logout` could not find a `user_sessions` row with the given id that
    also belongs to the calling actor -- deliberately the same error
    whether the session id does not exist at all or belongs to a different
    user, so `Logout` never confirms/denies another user's session id."""
