"""Task 8.4: `UnwiredStaffStatusAdapter` -- the intentionally-not-implemented
`StaffStatusPort` stub marking the one open seam this task leaves for the
Phase 10 composition root (tasks.md task 10.2, not yet built). Structural:
one behavior, one possible output (always raises) -- triangulation skipped,
see class docstring for why a second case would add no signal."""

import pytest

from app.modules.scheduling.adapters.outbound.staff_status.unwired_adapter import UnwiredStaffStatusAdapter


async def test_is_assignable_raises_not_implemented() -> None:
    adapter = UnwiredStaffStatusAdapter()

    with pytest.raises(NotImplementedError):
        await adapter.is_assignable("t1", "pr1")
