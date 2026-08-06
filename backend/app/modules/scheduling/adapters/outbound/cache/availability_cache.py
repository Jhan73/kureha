from datetime import date

from cachetools import TTLCache

from app.modules.scheduling.application.ports.driven.availability_repository import AvailabilityRepositoryPort
from app.modules.scheduling.domain.availability import AvailabilitySlot

_DEFAULT_MAXSIZE = 2048
_DEFAULT_TTL_SECONDS = 20


class CachedAvailabilityRepository:
    def __init__(
        self,
        inner: AvailabilityRepositoryPort,
        *,
        maxsize: int = _DEFAULT_MAXSIZE,
        ttl_seconds: float = _DEFAULT_TTL_SECONDS,
    ) -> None:
        self._inner = inner
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl_seconds)

    async def find_available_slots(
        self, tenant_id: str, *, site_id: str, professional_id: str, on_date: date
    ) -> list[AvailabilitySlot]:
        key = f"{tenant_id}:{site_id}:{professional_id}:{on_date.isoformat()}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        slots = await self._inner.find_available_slots(
            tenant_id, site_id=site_id, professional_id=professional_id, on_date=on_date
        )
        self._cache[key] = slots
        return slots

    async def get_slot(self, tenant_id: str, availability_id: str) -> AvailabilitySlot | None:
        """Never cached — reservation decisions need live status."""
        return await self._inner.get_slot(tenant_id, availability_id)

    async def reserve_slot(self, tenant_id: str, availability_id: str) -> AvailabilitySlot:
        return await self._inner.reserve_slot(tenant_id, availability_id)

    async def release_slot(self, tenant_id: str, availability_id: str) -> AvailabilitySlot:
        return await self._inner.release_slot(tenant_id, availability_id)
