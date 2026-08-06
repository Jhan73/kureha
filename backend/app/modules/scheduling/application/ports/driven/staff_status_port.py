from typing import Protocol


class StaffStatusPort(Protocol):
    async def is_assignable(self, tenant_id: str, professional_id: str) -> bool:
        """False if deactivated or no record; deny-by-default."""
        ...
