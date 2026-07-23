"""`CachedAvailabilityRepository` (design.md §18, tasks.md task 7.5):
in-process TTL decorator around an `AvailabilityRepositoryPort`, caching
ONLY `find_available_slots` -- the day-level listing design.md §18
classifies as "inofensivo" to serve stale (the `EXCLUDE USING gist`
constraint at booking time is the hard floor against a stale-but-since-taken
slot). Every other method (`get_slot`/`reserve_slot`/`release_slot`)
delegates straight through, uncached, per that same section: "NUNCA cachea"
a reservation decision.

**Key**: `f"{tenant_id}:{site_id}:{professional_id}:{on_date.isoformat()}"`
-- exactly the granularity design.md §18 specifies ("`tenant_id` solo no
alcanza"). Every key carries `tenant_id` as its first segment, so cache
entries never cross tenants even though the underlying `cachetools.TTLCache`
instance is shared process-wide (design.md §18's cross-cutting invariant:
"toda key de cache lleva `tenant_id` como prefijo").

**Bounds**: `ttl_seconds=20` (within design.md §18's "~15-30s" window) and
`maxsize=2048` (generous but finite -- design.md §18 explicitly calls out
that an unbounded cache is not acceptable even with a short TTL) are the
defaults; both are constructor-overridable for whoever wires the composition
root (tasks.md task 10.2) to tune against real site x resource x day volume."""

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
        """Never cached -- reservation decisions must read live status
        (design.md §18)."""
        return await self._inner.get_slot(tenant_id, availability_id)

    async def reserve_slot(self, tenant_id: str, availability_id: str) -> AvailabilitySlot:
        return await self._inner.reserve_slot(tenant_id, availability_id)

    async def release_slot(self, tenant_id: str, availability_id: str) -> AvailabilitySlot:
        return await self._inner.release_slot(tenant_id, availability_id)
