
class DomainError(Exception):
    """Base for domain/application errors; raise a subtype, never this."""


class NotFoundError(DomainError):
    """Missing or RLS-invisible to the caller (RLS usually yields zero rows)."""


class NotAuthorizedError(DomainError):
    """RBAC denial; RLS hides rows instead of raising."""


class ValidationError(DomainError):
    """Input violates a domain invariant."""


class ConflictError(DomainError):
    """Conflicts with existing state (e.g. double-booking / overlap)."""
