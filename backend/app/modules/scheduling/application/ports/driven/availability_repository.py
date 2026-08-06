from datetime import date
from typing import Protocol

from app.modules.scheduling.domain.availability import AvailabilitySlot


class AvailabilityRepositoryPort(Protocol):
    async def find_available_slots(
        self, tenant_id: str, *, site_id: str, professional_id: str, on_date: date
    ) -> list[AvailabilitySlot]:
        """Day listing for one professional; cache-eligible (booking still hits EXCLUDE)."""
        ...

    async def get_slot(self, tenant_id: str, availability_id: str) -> AvailabilitySlot | None:
        """Live PK lookup; never cached."""
        ...

    async def reserve_slot(self, tenant_id: str, availability_id: str) -> AvailabilitySlot:
        """Atomic available->reserved; SlotUnavailableError if not available."""
        ...

    async def release_slot(self, tenant_id: str, availability_id: str) -> AvailabilitySlot:
        """reserved->available when cancel/reschedule frees the slot."""
        ...
