"""Task 2.9: RLS isolation for staff_members/shifts (design.md §4.4's
"tenant+site+role" shape, migration 613f9ea3526f)."""

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from tests.rls.helpers import seed_professional, seed_shift, seed_site, seed_staff_member, seed_tenant, set_app_context

T0 = datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(hours=4)


async def test_staff_members_cross_tenant_select_returns_zero_rows(rls_conn) -> None:
    tenant_a = await seed_tenant(rls_conn)
    tenant_b = await seed_tenant(rls_conn)
    site_b = await seed_site(rls_conn, tenant_b)
    await seed_staff_member(rls_conn, tenant_b, site_b)

    site_a = await seed_site(rls_conn, tenant_a)
    await set_app_context(rls_conn, tenant_id=tenant_a, site_id=site_a, role="reception")
    rows = (await rls_conn.execute(sa.text("SELECT id FROM staff_members"))).all()
    assert rows == []


async def test_staff_members_cross_site_select_returns_zero_rows(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_a = await seed_site(rls_conn, tenant_id, name="Site A")
    site_b = await seed_site(rls_conn, tenant_id, name="Site B")
    await seed_staff_member(rls_conn, tenant_id, site_b)

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_a, role="reception")
    rows = (await rls_conn.execute(sa.text("SELECT id FROM staff_members"))).all()
    assert rows == []


async def test_staff_members_professional_sees_only_own_record(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    professional_a = await seed_professional(rls_conn, tenant_id, site_id, name="A")
    professional_b = await seed_professional(rls_conn, tenant_id, site_id, name="B")
    staff_a = await seed_staff_member(
        rls_conn, tenant_id, site_id, operational_role="professional", professional_id=professional_a
    )
    await seed_staff_member(
        rls_conn, tenant_id, site_id, operational_role="professional", professional_id=professional_b
    )

    await set_app_context(
        rls_conn, tenant_id=tenant_id, site_id=site_id, role="professional", professional_id=professional_a
    )
    rows = (await rls_conn.execute(sa.text("SELECT id FROM staff_members"))).all()
    assert [str(row.id) for row in rows] == [staff_a]


async def test_shifts_reject_cross_tenant(rls_conn) -> None:
    tenant_a = await seed_tenant(rls_conn)
    tenant_b = await seed_tenant(rls_conn)
    site_b = await seed_site(rls_conn, tenant_b)
    staff_b = await seed_staff_member(rls_conn, tenant_b, site_b)
    await seed_shift(
        rls_conn, tenant_b, site_b, staff_b, starts_at=T0, ends_at=T1
    )

    site_a = await seed_site(rls_conn, tenant_a)
    await set_app_context(rls_conn, tenant_id=tenant_a, site_id=site_a, role="reception")
    rows = (await rls_conn.execute(sa.text("SELECT id FROM shifts"))).all()
    assert rows == []


async def test_shifts_professional_sees_only_their_own_shift(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    professional_a = await seed_professional(rls_conn, tenant_id, site_id, name="A")
    professional_b = await seed_professional(rls_conn, tenant_id, site_id, name="B")
    staff_a = await seed_staff_member(
        rls_conn, tenant_id, site_id, operational_role="professional", professional_id=professional_a
    )
    staff_b = await seed_staff_member(
        rls_conn, tenant_id, site_id, operational_role="professional", professional_id=professional_b
    )
    shift_a = await seed_shift(
        rls_conn, tenant_id, site_id, staff_a, starts_at=T0, ends_at=T1
    )
    await seed_shift(
        rls_conn, tenant_id, site_id, staff_b, starts_at=T0, ends_at=T1
    )

    await set_app_context(
        rls_conn, tenant_id=tenant_id, site_id=site_id, role="professional", professional_id=professional_a
    )
    rows = (await rls_conn.execute(sa.text("SELECT id FROM shifts"))).all()
    assert [str(row.id) for row in rows] == [shift_a]
