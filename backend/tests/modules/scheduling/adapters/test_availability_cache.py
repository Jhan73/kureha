"""Task 7.5: `CachedAvailabilityRepository` -- in-process TTL cache wrapping
`AvailabilityRepositoryPort.find_available_slots` (design.md §18), key
`{tenant_id}:{site_id}:{resource_id}:{date}`, bounded `maxsize`. Every other
method (`get_slot`/`reserve_slot`/`release_slot`) delegates straight through,
uncached -- design.md §18: "NUNCA cachea" a reservation decision, only the
day-level listing. Fakes only, no DB."""

from datetime import date

from app.modules.scheduling.adapters.outbound.cache.availability_cache import CachedAvailabilityRepository
from app.modules.scheduling.domain.availability import AvailabilitySlot, AvailabilityStatus

_D0 = date(2026, 8, 1)
_D1 = date(2026, 8, 2)


def _slot(slot_id: str) -> AvailabilitySlot:
    from datetime import datetime, timezone

    return AvailabilitySlot(
        id=slot_id, tenant_id="t1", site_id="s1", professional_id="pr1",
        starts_at=datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        status=AvailabilityStatus.AVAILABLE,
    )


class _FakeAvailabilityRepository:
    def __init__(self) -> None:
        self.find_calls: list[tuple] = []
        self.reserve_calls: list[str] = []
        self.release_calls: list[str] = []
        self.get_calls: list[str] = []

    async def find_available_slots(self, tenant_id, *, site_id, professional_id, on_date):
        self.find_calls.append((tenant_id, site_id, professional_id, on_date))
        return [_slot("av1")]

    async def get_slot(self, tenant_id, availability_id):
        self.get_calls.append(availability_id)
        return _slot(availability_id)

    async def reserve_slot(self, tenant_id, availability_id):
        self.reserve_calls.append(availability_id)
        return _slot(availability_id)

    async def release_slot(self, tenant_id, availability_id):
        self.release_calls.append(availability_id)
        return _slot(availability_id)


async def test_find_available_slots_is_cached_by_full_key() -> None:
    inner = _FakeAvailabilityRepository()
    cache = CachedAvailabilityRepository(inner)

    first = await cache.find_available_slots("t1", site_id="s1", professional_id="pr1", on_date=_D0)
    second = await cache.find_available_slots("t1", site_id="s1", professional_id="pr1", on_date=_D0)

    assert first == second
    assert len(inner.find_calls) == 1


async def test_find_available_slots_cache_key_includes_tenant_site_resource_and_date() -> None:
    inner = _FakeAvailabilityRepository()
    cache = CachedAvailabilityRepository(inner)

    await cache.find_available_slots("t1", site_id="s1", professional_id="pr1", on_date=_D0)
    await cache.find_available_slots("t2", site_id="s1", professional_id="pr1", on_date=_D0)  # different tenant
    await cache.find_available_slots("t1", site_id="s2", professional_id="pr1", on_date=_D0)  # different site
    await cache.find_available_slots("t1", site_id="s1", professional_id="pr2", on_date=_D0)  # different resource
    await cache.find_available_slots("t1", site_id="s1", professional_id="pr1", on_date=_D1)  # different date

    assert len(inner.find_calls) == 5


async def test_cache_is_bounded_by_maxsize() -> None:
    inner = _FakeAvailabilityRepository()
    cache = CachedAvailabilityRepository(inner, maxsize=2, ttl_seconds=60)

    await cache.find_available_slots("t1", site_id="s1", professional_id="pr1", on_date=_D0)
    await cache.find_available_slots("t1", site_id="s1", professional_id="pr2", on_date=_D0)
    await cache.find_available_slots("t1", site_id="s1", professional_id="pr3", on_date=_D0)  # evicts pr1's entry

    assert len(cache._cache) <= 2  # noqa: SLF001 -- internal bound check, no public size accessor needed


class _TenantTaggedAvailabilityRepository:
    """Returns a result tagged with `tenant_id` itself, so a cross-tenant
    cache leak is observable as a WRONG VALUE, not just an extra call --
    the existing `test_find_available_slots_cache_key_includes_tenant_
    site_resource_and_date` above only proves the key differs (via call
    count); this proves the actual tenant-isolation invariant task 13.2
    asks for: two tenants querying the identical site/resource/date never
    read each other's cached slots."""

    def __init__(self) -> None:
        self.find_calls: list[tuple] = []

    async def find_available_slots(self, tenant_id, *, site_id, professional_id, on_date):
        self.find_calls.append((tenant_id, site_id, professional_id, on_date))
        return [_slot(f"av-{tenant_id}")]


async def test_two_tenants_never_share_a_cache_entry_for_the_same_site_resource_and_date() -> None:
    inner = _TenantTaggedAvailabilityRepository()
    cache = CachedAvailabilityRepository(inner)

    tenant_a_first = await cache.find_available_slots("tenant-a", site_id="s1", professional_id="pr1", on_date=_D0)
    tenant_b_first = await cache.find_available_slots("tenant-b", site_id="s1", professional_id="pr1", on_date=_D0)
    tenant_a_second = await cache.find_available_slots("tenant-a", site_id="s1", professional_id="pr1", on_date=_D0)
    tenant_b_second = await cache.find_available_slots("tenant-b", site_id="s1", professional_id="pr1", on_date=_D0)

    assert tenant_a_first != tenant_b_first
    assert tenant_a_second == tenant_a_first
    assert tenant_b_second == tenant_b_first
    assert len(inner.find_calls) == 2  # one live call per tenant; the repeats hit each tenant's OWN cache entry


async def test_get_slot_delegates_uncached() -> None:
    inner = _FakeAvailabilityRepository()
    cache = CachedAvailabilityRepository(inner)

    await cache.get_slot("t1", "av1")
    await cache.get_slot("t1", "av1")

    assert inner.get_calls == ["av1", "av1"]


async def test_reserve_slot_delegates_uncached() -> None:
    inner = _FakeAvailabilityRepository()
    cache = CachedAvailabilityRepository(inner)

    result = await cache.reserve_slot("t1", "av1")

    assert result.id == "av1"
    assert inner.reserve_calls == ["av1"]


async def test_release_slot_delegates_uncached() -> None:
    inner = _FakeAvailabilityRepository()
    cache = CachedAvailabilityRepository(inner)

    result = await cache.release_slot("t1", "av1")

    assert result.id == "av1"
    assert inner.release_calls == ["av1"]
