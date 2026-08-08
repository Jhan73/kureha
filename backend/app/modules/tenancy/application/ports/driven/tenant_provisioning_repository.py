from typing import Protocol


class TenantProvisioningRepositoryPort(Protocol):
    async def provision(
        self,
        *,
        tenant_id: str,
        name: str,
        site_id: str,
        site_name: str,
        admin_user_id: str,
        admin_email: str,
    ) -> None:
        """Creates `tenants`, the default `sites` row, the admin `users` row, and its
        `user_credentials` row (`auth_subject=NULL`) atomically.

        Raises `TenantAlreadyExistsError` if `tenant_id` already exists.
        """
        ...
