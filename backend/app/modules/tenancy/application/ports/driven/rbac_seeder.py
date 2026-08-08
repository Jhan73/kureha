from typing import Protocol


class RbacSeederPort(Protocol):
    async def seed_for_tenant(self, tenant_id: str) -> None:
        """Seeds the global action catalog (idempotent) and the default
        role -> permission grants for `tenant_id`.
        """
        ...
