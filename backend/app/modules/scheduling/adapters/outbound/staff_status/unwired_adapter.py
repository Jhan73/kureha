class UnwiredStaffStatusAdapter:
    async def is_assignable(self, tenant_id: str, professional_id: str) -> bool:
        raise NotImplementedError(
            "UnwiredStaffStatusAdapter is a placeholder -- wire a real StaffStatusPort before using."
        )
