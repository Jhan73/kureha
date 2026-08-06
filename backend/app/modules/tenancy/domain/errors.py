from app.shared_kernel.errors import NotAuthorizedError, NotFoundError


class TenantNotFoundError(NotFoundError):
    """No `tenants` row matches the given id."""


class TenantSuspendedError(NotAuthorizedError):
    """Tenant exists but is suspended; not NotFoundError."""
