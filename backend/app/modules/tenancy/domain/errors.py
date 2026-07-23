"""Tenancy-module error hierarchy, subclassing `shared_kernel.errors` the
same way `identity`/`rbac` do -- never a bare `DomainError`/generic 500."""

from app.shared_kernel.errors import NotAuthorizedError, NotFoundError


class TenantNotFoundError(NotFoundError):
    """No `tenants` row matches the given id."""


class TenantSuspendedError(NotAuthorizedError):
    """The `tenants` row was found but its live `status` is not `active`
    (design.md §4.1's `CHECK (status IN ('active','suspended'))`) --
    `TenantPolicy.is_usable` denied it. Modeled as `NotAuthorizedError`, not
    `NotFoundError`: the tenant genuinely exists, but nothing may act within
    it while suspended -- the same distinction `InactiveUserError` (identity)
    draws for a resolved-but-inactive `users` row."""
