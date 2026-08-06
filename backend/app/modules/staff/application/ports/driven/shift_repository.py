from datetime import datetime
from typing import Protocol

from app.modules.staff.domain.shift import Shift


class ShiftRepositoryPort(Protocol):
    async def create_shift(
        self, tenant_id: str, *, site_id: str, staff_member_id: str, starts_at: datetime, ends_at: datetime
    ) -> Shift:
        """Inserts a shift; raises ShiftOverlapError on EXCLUDE conflict."""
        ...

    async def get_shift(self, tenant_id: str, shift_id: str) -> Shift | None:
        """Tenant-scoped PK lookup; None if missing or RLS-hidden."""
        ...

    async def edit_shift(self, tenant_id: str, shift_id: str, *, starts_at: datetime, ends_at: datetime) -> Shift:
        """Moves window; same ShiftOverlapError contract as create_shift."""
        ...
