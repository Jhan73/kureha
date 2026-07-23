"""Task 8.3: `PostgresStaffRepository` -- `StaffRepositoryPort` adapter over
`staff_members` (design.md §4.4, migration d0e2489a94b8).

Uses `rls_conn` (the `app_runtime`/RLS-enforced connection), same contract as
`PostgresTenantRepository`/`PostgresSchedulingRepository`'s test modules."""

from tests.rls.helpers import seed_professional, seed_site, seed_tenant, set_app_context

from app.modules.staff.adapters.outbound.postgres.staff_repository import PostgresStaffRepository
from app.modules.staff.domain.staff_member import OperationalRole, StaffStatus


async def _seed_scenario(rls_conn):
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    professional_id = await seed_professional(rls_conn, tenant_id, site_id)
    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception")
    return tenant_id, site_id, professional_id


async def test_create_staff_member_inserts_an_active_row(rls_conn) -> None:
    tenant_id, site_id, professional_id = await _seed_scenario(rls_conn)
    repository = PostgresStaffRepository(rls_conn)

    staff = await repository.create_staff_member(
        tenant_id,
        site_id=site_id,
        name="Ana Torres",
        operational_role=OperationalRole.PROFESSIONAL,
        professional_id=professional_id,
    )

    assert staff.tenant_id == tenant_id
    assert staff.site_id == site_id
    assert staff.professional_id == professional_id
    assert staff.name == "Ana Torres"
    assert staff.operational_role == OperationalRole.PROFESSIONAL
    assert staff.status == StaffStatus.ACTIVE
    assert staff.deactivated_at is None


async def test_get_staff_member_returns_the_staff_member(rls_conn) -> None:
    tenant_id, site_id, professional_id = await _seed_scenario(rls_conn)
    repository = PostgresStaffRepository(rls_conn)
    created = await repository.create_staff_member(
        tenant_id, site_id=site_id, name="Ana Torres", operational_role=OperationalRole.PROFESSIONAL,
        professional_id=professional_id,
    )

    fetched = await repository.get_staff_member(tenant_id, created.id)

    assert fetched == created


async def test_get_staff_member_returns_none_for_unknown_id(rls_conn) -> None:
    tenant_id, *_ = await _seed_scenario(rls_conn)
    repository = PostgresStaffRepository(rls_conn)

    assert await repository.get_staff_member(tenant_id, "00000000-0000-0000-0000-000000000000") is None


async def test_deactivate_staff_member_sets_status_inactive_never_deletes(rls_conn) -> None:
    tenant_id, site_id, professional_id = await _seed_scenario(rls_conn)
    repository = PostgresStaffRepository(rls_conn)
    created = await repository.create_staff_member(
        tenant_id, site_id=site_id, name="Ana Torres", operational_role=OperationalRole.PROFESSIONAL,
        professional_id=professional_id,
    )

    deactivated = await repository.deactivate_staff_member(tenant_id, created.id)

    assert deactivated.status == StaffStatus.INACTIVE
    assert deactivated.deactivated_at is not None
    # The row still exists (deactivate never deletes, design.md §6).
    refetched = await repository.get_staff_member(tenant_id, created.id)
    assert refetched is not None
    assert refetched.status == StaffStatus.INACTIVE
