from datetime import datetime, timedelta, timezone

import pytest

from tests.rls.helpers import seed_professional, seed_site, seed_staff_member, seed_tenant, set_app_context

from app.modules.staff.adapters.outbound.postgres.shift_repository import PostgresShiftRepository
from app.modules.staff.domain.errors import ShiftOverlapError

T0 = datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(hours=6)
T2 = T0 + timedelta(hours=8)


async def _seed_scenario(rls_conn):
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    professional_id = await seed_professional(rls_conn, tenant_id, site_id)
    staff_member_id = await seed_staff_member(rls_conn, tenant_id, site_id, professional_id=professional_id)
    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception")
    return tenant_id, site_id, staff_member_id


async def test_create_shift_inserts_a_row(rls_conn) -> None:
    tenant_id, site_id, staff_member_id = await _seed_scenario(rls_conn)
    repository = PostgresShiftRepository(rls_conn)

    shift = await repository.create_shift(
        tenant_id, site_id=site_id, staff_member_id=staff_member_id, starts_at=T0, ends_at=T1
    )

    assert shift.tenant_id == tenant_id
    assert shift.site_id == site_id
    assert shift.staff_member_id == staff_member_id
    assert shift.starts_at == T0
    assert shift.ends_at == T1


async def test_create_shift_raises_overlap_on_conflicting_window(rls_conn) -> None:
    tenant_id, site_id, staff_member_id = await _seed_scenario(rls_conn)
    repository = PostgresShiftRepository(rls_conn)

    async with rls_conn.begin_nested():
        await repository.create_shift(tenant_id, site_id=site_id, staff_member_id=staff_member_id, starts_at=T0, ends_at=T1)

    with pytest.raises(ShiftOverlapError):
        async with rls_conn.begin_nested():
            await repository.create_shift(
                tenant_id, site_id=site_id, staff_member_id=staff_member_id,
                starts_at=T0 + timedelta(hours=2), ends_at=T2,
            )


async def test_get_shift_returns_the_shift(rls_conn) -> None:
    tenant_id, site_id, staff_member_id = await _seed_scenario(rls_conn)
    repository = PostgresShiftRepository(rls_conn)
    created = await repository.create_shift(
        tenant_id, site_id=site_id, staff_member_id=staff_member_id, starts_at=T0, ends_at=T1
    )

    fetched = await repository.get_shift(tenant_id, created.id)

    assert fetched == created


async def test_get_shift_returns_none_for_unknown_id(rls_conn) -> None:
    tenant_id, *_ = await _seed_scenario(rls_conn)
    repository = PostgresShiftRepository(rls_conn)

    assert await repository.get_shift(tenant_id, "00000000-0000-0000-0000-000000000000") is None


async def test_edit_shift_moves_the_time_window(rls_conn) -> None:
    tenant_id, site_id, staff_member_id = await _seed_scenario(rls_conn)
    repository = PostgresShiftRepository(rls_conn)
    created = await repository.create_shift(
        tenant_id, site_id=site_id, staff_member_id=staff_member_id, starts_at=T0, ends_at=T1
    )

    edited = await repository.edit_shift(tenant_id, created.id, starts_at=T1, ends_at=T2)

    assert edited.id == created.id
    assert edited.starts_at == T1
    assert edited.ends_at == T2


async def test_edit_shift_raises_overlap_when_it_collides_with_another_shift(rls_conn) -> None:
    tenant_id, site_id, staff_member_id = await _seed_scenario(rls_conn)
    repository = PostgresShiftRepository(rls_conn)
    await repository.create_shift(tenant_id, site_id=site_id, staff_member_id=staff_member_id, starts_at=T0, ends_at=T1)
    other = await repository.create_shift(tenant_id, site_id=site_id, staff_member_id=staff_member_id, starts_at=T1, ends_at=T2)

    with pytest.raises(ShiftOverlapError):
        async with rls_conn.begin_nested():
            await repository.edit_shift(
                tenant_id, other.id, starts_at=T0 + timedelta(hours=2), ends_at=T2
            )
