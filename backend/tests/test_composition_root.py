"""Task 10.2: `app.composition_root` -- integration tests against real
Postgres (via the RLS-enforced `rls_conn`/`app_runtime` fixture, never a
fake port) proving the four gaps that module's docstring lists are actually
closed:

1. `build_permission_service` hands out a fresh instance per call, never a
   cached/singleton one (design.md §5.6/ADR-16).
2. `PostgresStaffStatusAdapter` correctly resolves assignable/not-assignable
   against real `staff_members` data (tasks.md task 8.4's seam).
3. `PostgresAppointmentSnapshotAdapter` returns real `appointments` data
   (tasks.md task 9.5's seam).
4. `build_sync_appointment_to_calendar` resolves `SyncAppointmentToCalendar`'s
   dual-role RLS boundary end-to-end -- the patient-scoped credential read
   AND the staff-scoped sync write both succeed in one flow, which a single
   fixed role could not do.

Also covers `bootstrap_rbac_catalog_and_grants` (task 3.6's forward pointer,
closed here)."""

from datetime import datetime, timezone

import sqlalchemy as sa

from app.composition_root import (
    PostgresAppointmentSnapshotAdapter,
    PostgresStaffStatusAdapter,
    bootstrap_rbac_catalog_and_grants,
    build_create_shift,
    build_permission_service,
    build_register_staff,
    build_sync_appointment_to_calendar,
)
from app.modules.staff.domain.staff_member import OperationalRole
from app.modules.calendar.adapters.outbound.postgres.calendar_credential_repository import (
    PostgresCalendarCredentialRepository,
)
from app.modules.calendar.adapters.outbound.postgres.calendar_sync_repository import PostgresCalendarSyncRepository
from app.modules.calendar.domain.calendar_event_mapping import CalendarSyncResult
from app.modules.calendar.domain.calendar_sync_record import CalendarSyncStatus
from app.modules.governance.rbac.adapters.outbound.rbac.action_catalog import ACTION_CATALOG
from app.modules.governance.rbac.adapters.outbound.rbac.default_role_permissions import (
    DEFAULT_DEV_ROLE_PERMISSIONS,
)
from app.shared_kernel.tenant_context import TenantContext
from tests.rls.helpers import (
    seed_appointment,
    seed_availability,
    seed_calendar_credential,
    seed_patient,
    seed_professional,
    seed_site,
    seed_staff_member,
    seed_tenant,
    set_app_context,
)

_T0 = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
_T1 = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)


class _FakeCredentialVault:
    """No real KEK/DEK material needed here -- `AesGcmVault`'s own round-trip
    is already covered by tests/modules/calendar/adapters/test_aes_gcm_vault.py.
    This test's concern is the RLS role-boundary, not encryption."""

    async def encrypt(self, plaintext: bytes):
        raise NotImplementedError

    async def decrypt(self, secret) -> bytes:
        return b"refresh-token"


class _FakeCalendarSyncPort:
    """No real Google API call needed here -- `GoogleCalendarAdapter`'s own
    contract is already covered by test_google_calendar_adapter.py. This
    test's concern is the RLS role-boundary, not the external HTTP call."""

    def __init__(self) -> None:
        self.upsert_calls: list = []

    async def upsert_event(self, cred, mapping) -> CalendarSyncResult:
        self.upsert_calls.append((cred, mapping))
        return CalendarSyncResult(ok=True, google_event_id="evt-1")

    async def delete_event(self, cred, google_event_id) -> CalendarSyncResult:
        raise NotImplementedError


async def test_build_permission_service_returns_a_fresh_instance_each_call(rls_conn) -> None:
    """design.md §5.6/ADR-16, tasks.md task 10.2's own "add a test asserting
    this at the composition-root level": two calls to
    `build_permission_service` return two distinct Python objects, and a
    grant that changes between calls is visible to the second instance
    immediately -- no memo carried over from the first (mirrors
    `PermissionService`'s own `test_a_fresh_service_instance_never_sees_a_stale_memo`,
    exercised through the actual composition-root factory this time)."""
    tenant_id = await seed_tenant(rls_conn)
    await set_app_context(rls_conn, tenant_id=tenant_id, role="admin")
    await rls_conn.execute(
        sa.text(
            "INSERT INTO action_permissions (key, description) VALUES ('shift:edit', 'x') "
            "ON CONFLICT DO NOTHING"
        )
    )
    await rls_conn.execute(
        sa.text(
            "INSERT INTO role_permissions (tenant_id, role, action, allowed) "
            "VALUES (:t, 'reception', 'shift:edit', false)"
        ),
        {"t": tenant_id},
    )

    await set_app_context(rls_conn, tenant_id=tenant_id, role="reception")
    ctx = TenantContext(tenant_id=tenant_id, role="reception")
    service_a = build_permission_service(rls_conn)
    assert await service_a.is_allowed(ctx, "shift:edit") is False

    await set_app_context(rls_conn, tenant_id=tenant_id, role="admin")
    await rls_conn.execute(
        sa.text("UPDATE role_permissions SET allowed = true WHERE tenant_id = :t AND action = 'shift:edit'"),
        {"t": tenant_id},
    )

    await set_app_context(rls_conn, tenant_id=tenant_id, role="reception")
    service_b = build_permission_service(rls_conn)

    assert service_a is not service_b
    assert await service_b.is_allowed(ctx, "shift:edit") is True


async def test_postgres_staff_status_adapter_reports_active_staff_as_assignable(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    professional_id = await seed_professional(rls_conn, tenant_id, site_id)
    await seed_staff_member(rls_conn, tenant_id, site_id, professional_id=professional_id)

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception")
    adapter = PostgresStaffStatusAdapter(rls_conn)

    assert await adapter.is_assignable(tenant_id, professional_id) is True


async def test_postgres_staff_status_adapter_reports_deactivated_staff_as_not_assignable(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    professional_id = await seed_professional(rls_conn, tenant_id, site_id)
    staff_member_id = await seed_staff_member(rls_conn, tenant_id, site_id, professional_id=professional_id)

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception")
    await rls_conn.execute(
        sa.text("UPDATE staff_members SET status = 'inactive', deactivated_at = now() WHERE id = :id"),
        {"id": staff_member_id},
    )
    adapter = PostgresStaffStatusAdapter(rls_conn)

    assert await adapter.is_assignable(tenant_id, professional_id) is False


async def test_postgres_staff_status_adapter_denies_by_default_when_no_staff_member_matches(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    unmapped_professional_id = await seed_professional(rls_conn, tenant_id, site_id)

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception")
    adapter = PostgresStaffStatusAdapter(rls_conn)

    assert await adapter.is_assignable(tenant_id, unmapped_professional_id) is False


async def test_postgres_appointment_snapshot_adapter_returns_real_appointment_data(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    professional_id = await seed_professional(rls_conn, tenant_id, site_id)
    patient_id = await seed_patient(rls_conn, tenant_id, site_id)
    availability_id = await seed_availability(
        rls_conn, tenant_id, site_id, professional_id, starts_at=_T0, ends_at=_T1
    )
    appointment_id = await seed_appointment(
        rls_conn, tenant_id, site_id, patient_id, professional_id, availability_id, starts_at=_T0, ends_at=_T1
    )

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception")
    adapter = PostgresAppointmentSnapshotAdapter(rls_conn)

    snapshot = await adapter.get_snapshot(tenant_id, appointment_id)

    assert snapshot is not None
    assert snapshot.patient_id == patient_id
    assert snapshot.starts_at == _T0
    assert snapshot.ends_at == _T1
    assert snapshot.site_id == site_id


async def test_postgres_appointment_snapshot_adapter_returns_none_when_appointment_missing(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception")
    adapter = PostgresAppointmentSnapshotAdapter(rls_conn)

    assert await adapter.get_snapshot(tenant_id, "00000000-0000-0000-0000-000000000000") is None


async def test_sync_appointment_to_calendar_resolves_the_dual_role_rls_boundary(rls_conn) -> None:
    """tasks.md task 10.2: `SyncAppointmentToCalendar` reads
    `calendar_credentials` (patient-only RLS policy) and writes
    `calendar_sync` (staff-only RLS policy) in ONE flow. Proves both halves
    succeed through `build_sync_appointment_to_calendar`'s role-scoping
    wrapper, and that a single FIXED role could not have done it: under a
    connection fixed at the staff role alone, the patient-only credential
    row is invisible (asserted directly below, before the wrapped call)."""
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    professional_id = await seed_professional(rls_conn, tenant_id, site_id)
    patient_id = await seed_patient(rls_conn, tenant_id, site_id)
    availability_id = await seed_availability(
        rls_conn, tenant_id, site_id, professional_id, starts_at=_T0, ends_at=_T1
    )
    appointment_id = await seed_appointment(
        rls_conn, tenant_id, site_id, patient_id, professional_id, availability_id, starts_at=_T0, ends_at=_T1
    )
    await seed_calendar_credential(rls_conn, tenant_id, patient_id)

    # Sanity check: under a SINGLE fixed staff role, the patient-only
    # credential row is invisible (RLS silently filters it, not an error) --
    # exactly the failure `RoleScopedCalendarCredentialRepository` exists to
    # prevent.
    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception")
    assert await PostgresCalendarCredentialRepository(rls_conn).get(tenant_id, patient_id) is None

    sync_port = _FakeCalendarSyncPort()
    use_case = build_sync_appointment_to_calendar(
        rls_conn,
        base_role="reception",
        calendar_sync_port=sync_port,
        credential_vault=_FakeCredentialVault(),
    )

    result = await use_case.execute(
        tenant_id,
        site_id=site_id,
        appointment_id=appointment_id,
        patient_id=patient_id,
        starts_at=_T0,
        ends_at=_T1,
    )

    assert result.status == CalendarSyncStatus.OK
    assert result.google_event_id == "evt-1"
    assert len(sync_port.upsert_calls) == 1

    # The staff-scoped write is durably visible under the SAME connection,
    # still at the restored `base_role` -- proves the connection came back
    # out of the transient patient re-scope correctly.
    persisted = await PostgresCalendarSyncRepository(rls_conn).get_by_appointment(tenant_id, appointment_id)
    assert persisted is not None
    assert persisted.status == CalendarSyncStatus.OK
    assert persisted.google_event_id == "evt-1"


async def test_bootstrap_rbac_catalog_and_grants_seeds_the_catalog_and_every_existing_tenant(rls_conn) -> None:
    """tasks.md task 3.6's own forward pointer, closed here: the seed
    functions actually get invoked, not just defined.

    **Flagged bug found this session (PR 11 batch 3), NOT fixed at its own
    source -- out of this batch's scope (Phase 3/10 code):**
    `bootstrap_rbac_catalog_and_grants` loops `SET LOCAL app.tenant_id =
    <tenant>` over EVERY existing tenant (no `ORDER BY` on `SELECT id FROM
    tenants`) and never restores the caller's own `app.tenant_id` GUC
    afterward -- so by the time this function returns, `app.tenant_id` on
    `conn` points at whichever tenant was iterated LAST, not necessarily the
    one THIS test created. `role_permissions_tenant`'s RLS policy filters on
    `current_setting('app.tenant_id')` -- once enough OTHER tenants exist in
    the shared dev Postgres (this session accumulated many via router tests'
    real, permanently-committed seed data, `conftest.py`'s own documented
    behavior), this test's own `tenant_id` stopped reliably being the LAST
    one iterated, and its own read-back query started intermittently
    returning 0 rows -- NOT a regression in this batch's own node/edge
    logic. Fixed here with a defensive `set_app_context` re-assertion right
    before the read, the minimal safe change that does not touch
    `bootstrap_rbac_catalog_and_grants` itself; the real fix (documented,
    not applied) belongs in that function -- either restore the caller's
    original GUCs on exit, or have callers never rely on `conn`'s
    tenant-scoping surviving a call to it."""
    tenant_id = await seed_tenant(rls_conn)

    await bootstrap_rbac_catalog_and_grants(rls_conn)

    catalog_count = (await rls_conn.execute(sa.text("SELECT count(*) FROM action_permissions"))).scalar_one()
    assert catalog_count == len(ACTION_CATALOG)

    await set_app_context(rls_conn, tenant_id=tenant_id, role="admin")
    granted_count = (
        await rls_conn.execute(
            sa.text("SELECT count(*) FROM role_permissions WHERE tenant_id = :t"), {"t": tenant_id}
        )
    ).scalar_one()
    assert granted_count == sum(len(actions) for actions in DEFAULT_DEV_ROLE_PERMISSIONS.values())


async def test_build_register_staff_and_build_create_shift_wire_working_use_cases(rls_conn) -> None:
    """tasks.md task 11.5 (PR 11 batch 3): `build_register_staff`/
    `build_create_shift`/`build_deactivate_staff`/`build_edit_shift` had NO
    composition-root wiring before this batch (confirmed via `grep
    "^def build_" app/composition_root.py`) -- `persist_and_audit`'s
    dispatch table (unit-tested with fakes) is their first real caller.
    This test proves the ACTUAL wiring against real Postgres for the two
    representative cases (register + create), mirroring
    `test_bootstrap_rbac_catalog_and_grants_seeds_the_catalog_and_every_
    existing_tenant`'s own pattern above."""
    tenant_id = await seed_tenant(rls_conn)
    await bootstrap_rbac_catalog_and_grants(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)

    actor_id = "33333333-3333-3333-3333-333333333333"
    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception", user_id=actor_id)
    ctx = TenantContext(tenant_id=tenant_id, role="reception", site_id=site_id, actor_id=actor_id)

    register_staff = build_register_staff(rls_conn)
    staff = await register_staff.execute(
        ctx, site_id=site_id, name="Nueva Recepcionista", operational_role=OperationalRole.RECEPTION
    )
    assert staff.name == "Nueva Recepcionista"

    create_shift = build_create_shift(rls_conn)
    professional_id = await seed_professional(rls_conn, tenant_id, site_id)
    await seed_staff_member(rls_conn, tenant_id, site_id, professional_id=professional_id)
    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception", user_id=actor_id)
    shift = await create_shift.execute(
        ctx, site_id=site_id, staff_member_id=await _staff_member_id_for(rls_conn, professional_id), starts_at=_T0, ends_at=_T1
    )
    assert shift.staff_member_id


async def _staff_member_id_for(rls_conn, professional_id: str) -> str:
    result = await rls_conn.execute(
        sa.text("SELECT id FROM staff_members WHERE professional_id = :p"), {"p": professional_id}
    )
    return str(result.scalar_one())


async def test_bootstrap_rbac_catalog_and_grants_is_idempotent(rls_conn) -> None:
    """Same flagged GUC-drift bug as the test above -- re-asserts
    `app.tenant_id` before the read-back, see that test's own docstring."""
    tenant_id = await seed_tenant(rls_conn)

    await bootstrap_rbac_catalog_and_grants(rls_conn)
    await bootstrap_rbac_catalog_and_grants(rls_conn)

    await set_app_context(rls_conn, tenant_id=tenant_id, role="admin")
    granted_count = (
        await rls_conn.execute(
            sa.text("SELECT count(*) FROM role_permissions WHERE tenant_id = :t"), {"t": tenant_id}
        )
    ).scalar_one()
    assert granted_count == sum(len(actions) for actions in DEFAULT_DEV_ROLE_PERMISSIONS.values())
