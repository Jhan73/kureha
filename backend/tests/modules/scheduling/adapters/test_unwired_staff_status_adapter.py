import pytest

from app.modules.scheduling.adapters.outbound.staff_status.unwired_adapter import UnwiredStaffStatusAdapter


async def test_is_assignable_raises_not_implemented() -> None:
    adapter = UnwiredStaffStatusAdapter()

    with pytest.raises(NotImplementedError):
        await adapter.is_assignable("t1", "pr1")
