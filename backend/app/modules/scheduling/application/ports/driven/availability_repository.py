"""`AvailabilityRepositoryPort` (design.md §4.1/§18): `availability` access
for the scheduling module's use cases. Implemented in MVP by
`PostgresAvailabilityRepository` (adapters/outbound/postgres/
availability_repository.py, tasks.md 7.4) and wrapped by
`CachedAvailabilityRepository` (adapters/outbound/cache/availability_cache.py,
tasks.md 7.5) for the read-only `find_available_slots` lookup."""

from datetime import date
from typing import Protocol

from app.modules.scheduling.domain.availability import AvailabilitySlot


class AvailabilityRepositoryPort(Protocol):
    async def find_available_slots(
        self, tenant_id: str, *, site_id: str, professional_id: str, on_date: date
    ) -> list[AvailabilitySlot]:
        """Slots with `status='available'` for one professional on one
        calendar day -- the exact granularity design.md §18 specifies for
        the TTL cache key (`tenant_id:site_id:resource_id:date`). Inoffensive
        to cache: a stale "available" slot fails safe at booking time via the
        `EXCLUDE USING gist` floor (design.md §18's cache table)."""
        ...

    async def get_slot(self, tenant_id: str, availability_id: str) -> AvailabilitySlot | None:
        """Tenant-scoped lookup by primary key. NEVER cached -- reservation
        decisions must read live status, only the day-level listing above is
        cache-eligible."""
        ...

    async def reserve_slot(self, tenant_id: str, availability_id: str) -> AvailabilitySlot:
        """Atomically flips `status: 'available' -> 'reserved'`. Raises
        `SlotUnavailableError` when the slot does not exist, or exists but is
        no longer `available` (already reserved/blocked, or raced by a
        concurrent request) -- the `UPDATE ... WHERE status = 'available'`
        pattern makes this check-and-set atomic at the DB level, no
        SELECT-then-UPDATE race window."""
        ...

    async def release_slot(self, tenant_id: str, availability_id: str) -> AvailabilitySlot:
        """Flips `status: 'reserved' -> 'available'` -- used when a
        reschedule/cancel frees up the appointment's original slot."""
        ...
