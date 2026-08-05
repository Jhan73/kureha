"""Identity-module error hierarchy (design.md §17), subclassing
`shared_kernel.errors.NotAuthorizedError` the same way `rbac`'s
`ActionNotPermittedError` does -- authn/session failures are a form of "not
authorized", never surfaced as a generic 500.

`EmailAlreadyRegisteredError` (added this session, staff-invite batch):
subclasses `ConflictError`, not `NotAuthorizedError` -- an email collision on
`user_credentials` is a state conflict (design.md §21.1's `validation`
category, `ConflictError`'s own docstring: "conflicts with existing domain
state"), not an authn/authz failure. No new `errors.py` `_MAPPINGS` entry
needed: that module's MRO-walk resolution already covers any `ConflictError`
subclass via the generic `ConflictError` mapping (409, `conflict`)."""

from app.shared_kernel.errors import ConflictError, NotAuthorizedError, NotFoundError


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


class EmailAlreadyRegisteredError(ConflictError):
    """`ProvisionStaffIdentity` found an existing `user_credentials` row for
    the invited email within this tenant (`UserDirectoryPort.find_by_email`)
    -- distinct from `InvalidCredentialsError`'s anti-enumeration posture:
    THIS check runs behind an authenticated, RBAC-gated admin/reception
    request (`staff:register`), not a pre-auth attempt an anonymous attacker
    controls, so confirming "this email is already registered" is not an
    enumeration leak here."""


class SessionNotFoundError(NotFoundError):
    """`Logout` could not find a `user_sessions` row with the given id that
    also belongs to the calling actor -- deliberately the same error
    whether the session id does not exist at all or belongs to a different
    user, so `Logout` never confirms/denies another user's session id."""
