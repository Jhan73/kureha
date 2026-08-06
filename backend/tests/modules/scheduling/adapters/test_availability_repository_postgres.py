from datetime import datetime, timedelta, timezone

from tests.rls.helpers import seed_professional, seed_site, seed_tenant, set_app_context

from app.modules.scheduling.adapters.outbound.postgres.availability_repository import (
    PostgresAvailabilityRepository,
)
from app.modules.scheduling.domain.availability import AvailabilityStatus
from app.modules.scheduling.domain.errors import SlotUnavailableError

import pytest

T0 = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(hours=1)
T2 = T0 + timedelta(hours=2)


async def _seed_scenario(rls_conn):
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    professional_id = await seed_professional(rls_conn, tenant_id, site_id)
    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception")
    return tenant_id, site_id, professional_id


async def _insert_slot(rls_conn, tenant_id, site_id, professional_id, *, starts_at, ends_at):
    import sqlalchemy as sa

    result = await rls_conn.execute(
        sa.text(
            "INSERT INTO availability (tenant_id, site_id, professional_id, starts_at, ends_at) "
            "VALUES (:t, :s, :p, :starts_at, :ends_at) RETURNING id"
        ),
        {"t": tenant_id, "s": site_id, "p": professional_id, "starts_at": starts_at, "ends_at": ends_at},
    )
    return str(result.scalar_one())


async def test_get_slot_returns_the_slot(rls_conn) -> None:
    tenant_id, site_id, professional_id = await _seed_scenario(rls_conn)
    slot_id = await _insert_slot(rls_conn, tenant_id, site_id, professional_id, starts_at=T0, ends_at=T1)

    repository = PostgresAvailabilityRepository(rls_conn)
    slot = await repository.get_slot(tenant_id, slot_id)

    assert slot is not None
    assert slot.id == slot_id
    assert slot.tenant_id == tenant_id
    assert slot.site_id == site_id
    assert slot.professional_id == professional_id
    assert slot.status == AvailabilityStatus.AVAILABLE


async def test_get_slot_returns_none_for_unknown_id(rls_conn) -> None:
    tenant_id, _, _ = await _seed_scenario(rls_conn)
    repository = PostgresAvailabilityRepository(rls_conn)

    assert await repository.get_slot(tenant_id, "00000000-0000-0000-0000-000000000000") is None


async def test_find_available_slots_filters_by_resource_and_date(rls_conn) -> None:
    tenant_id, site_id, professional_id = await _seed_scenario(rls_conn)
    other_professional = await seed_professional(rls_conn, tenant_id, site_id, name="Other")
    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception")

    matching = await _insert_slot(rls_conn, tenant_id, site_id, professional_id, starts_at=T0, ends_at=T1)
    await _insert_slot(rls_conn, tenant_id, site_id, professional_id, starts_at=T1, ends_at=T2)
    await _insert_slot(
        rls_conn, tenant_id, site_id, other_professional,
        starts_at=T0 + timedelta(days=1), ends_at=T1 + timedelta(days=1),
    )
    await _insert_slot(rls_conn, tenant_id, site_id, other_professional, starts_at=T0, ends_at=T1)

    repository = PostgresAvailabilityRepository(rls_conn)
    slots = await repository.find_available_slots(
        tenant_id, site_id=site_id, professional_id=professional_id, on_date=T0.date()
    )

    assert len(slots) == 2
    assert slots[0].id == matching
    assert {slot.professional_id for slot in slots} == {professional_id}


async def test_reserve_slot_flips_status_to_reserved(rls_conn) -> None:
    tenant_id, site_id, professional_id = await _seed_scenario(rls_conn)
    slot_id = await _insert_slot(rls_conn, tenant_id, site_id, professional_id, starts_at=T0, ends_at=T1)

    repository = PostgresAvailabilityRepository(rls_conn)
    reserved = await repository.reserve_slot(tenant_id, slot_id)

    assert reserved.status == AvailabilityStatus.RESERVED
    refetched = await repository.get_slot(tenant_id, slot_id)
    assert refetched.status == AvailabilityStatus.RESERVED


async def test_reserve_slot_raises_when_already_reserved(rls_conn) -> None:
    tenant_id, site_id, professional_id = await _seed_scenario(rls_conn)
    slot_id = await _insert_slot(rls_conn, tenant_id, site_id, professional_id, starts_at=T0, ends_at=T1)
    repository = PostgresAvailabilityRepository(rls_conn)
    await repository.reserve_slot(tenant_id, slot_id)

    with pytest.raises(SlotUnavailableError):
        await repository.reserve_slot(tenant_id, slot_id)


async def test_reserve_slot_raises_when_unknown_id(rls_conn) -> None:
    tenant_id, _, _ = await _seed_scenario(rls_conn)
    repository = PostgresAvailabilityRepository(rls_conn)

    with pytest.raises(SlotUnavailableError):
        await repository.reserve_slot(tenant_id, "00000000-0000-0000-0000-000000000000")


async def test_release_slot_flips_status_back_to_available(rls_conn) -> None:
    tenant_id, site_id, professional_id = await _seed_scenario(rls_conn)
    slot_id = await _insert_slot(rls_conn, tenant_id, site_id, professional_id, starts_at=T0, ends_at=T1)
    repository = PostgresAvailabilityRepository(rls_conn)
    await repository.reserve_slot(tenant_id, slot_id)

    released = await repository.release_slot(tenant_id, slot_id)

    assert released.status == AvailabilityStatus.AVAILABLE
