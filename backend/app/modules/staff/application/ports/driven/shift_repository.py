"""`ShiftRepositoryPort` (design.md §4.4): `shifts` access for the staff
module's use cases. Implemented in MVP by `PostgresShiftRepository`
(adapters/outbound/postgres/shift_repository.py), RLS-scoped (tasks.md task
8.3)."""

from datetime import datetime
from typing import Protocol

from app.modules.staff.domain.shift import Shift


class ShiftRepositoryPort(Protocol):
    async def create_shift(
        self, tenant_id: str, *, site_id: str, staff_member_id: str, starts_at: datetime, ends_at: datetime
    ) -> Shift:
        """Inserts a new `shifts` row.

        Raises `ShiftOverlapError` when the `EXCLUDE USING gist` anti-overlap
        constraint (design.md §4.4) rejects the insert -- the definitive,
        race-safe floor for concurrent shift edits of the same staff member
        (spec `staff-scheduling` -> "Concurrent shift edits do not create
        overlap")."""
        ...

    async def get_shift(self, tenant_id: str, shift_id: str) -> Shift | None:
        """Tenant-scoped lookup by primary key. Returns `None` when no row
        matches (or the row is invisible under the caller's RLS scope)."""
        ...

    async def edit_shift(self, tenant_id: str, shift_id: str, *, starts_at: datetime, ends_at: datetime) -> Shift:
        """Moves the shift to a new time window. Same `EXCLUDE USING
        gist`-backed `ShiftOverlapError` contract as `create_shift`."""
        ...
