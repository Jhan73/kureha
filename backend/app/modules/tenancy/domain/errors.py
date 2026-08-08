from app.shared_kernel.errors import ConflictError, NotAuthorizedError, NotFoundError


class TenantNotFoundError(NotFoundError):
    """No `tenants` row matches the given id."""


class TenantSuspendedError(NotAuthorizedError):
    """Tenant exists but is suspended; not NotFoundError."""


class TenantAlreadyExistsError(ConflictError):
    """A `tenants` row with the given id already exists."""
