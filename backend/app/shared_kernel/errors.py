"""`DomainError` hierarchy shared by every module (design.md §2.5).

Kept intentionally small and generic -- these are the error shapes every
module's domain/application layer needs (not found, not authorized, invalid
input, conflicting state), never a business-specific one (that belongs to
the module that raises it, e.g. `rbac.ActionNotPermittedError` subclasses
`NotAuthorizedError` from this module instead of duplicating the hierarchy).
"""


class DomainError(Exception):
    """Base class for every domain/application-level error in Kureha.

    Never raised directly -- always one of the subtypes below, or a
    module-specific subclass of one of them.
    """


class NotFoundError(DomainError):
    """The requested domain object does not exist (or is not visible to the
    caller -- RLS and this error are independent: a row hidden by RLS never
    reaches application code to raise this in the first place)."""


class NotAuthorizedError(DomainError):
    """The actor is not authorized to perform the requested operation.

    This is RBAC's plane (design.md §5.1), not RLS's -- RLS violations never
    surface as Python exceptions, they surface as zero rows returned by
    Postgres.
    """


class ValidationError(DomainError):
    """The input to a use case violates a domain invariant."""


class ConflictError(DomainError):
    """The requested operation conflicts with existing domain state (e.g. a
    double-booking or an overlapping shift already rejected by a DB
    constraint, surfaced back through the domain layer as this type)."""
