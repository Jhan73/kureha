from datetime import datetime, timezone

import sqlalchemy as sa

from app.composition_root import (
    PostgresAppointmentSnapshotAdapter,
    PostgresStaffStatusAdapter,
    bootstrap_rbac_catalog_and_grants,
    build_affirmation_classifier,
    build_auth_account_rate_limiter,
    build_chat_rate_limiter,
    build_create_shift,
    build_direct_response,
    build_get_tenant,
    build_intent_classifier,
    build_permission_service,
    build_register_staff,
    build_reminder_planner,
    build_scheduling_planner,
    build_scope_policy,
    build_staff_planner,
    build_suggestion_generator,
    build_sync_appointment_to_calendar,
)
from app.modules.governance.scope.adapters.outbound.anthropic.anthropic_scope_policy import AnthropicScopePolicy
from app.platform.inbound.graph.adapters.anthropic_affirmation_classifier import AnthropicAffirmationClassifier
from app.platform.inbound.graph.adapters.anthropic_direct_response import AnthropicDirectResponse
from app.platform.inbound.graph.adapters.anthropic_intent_classifier import AnthropicIntentClassifier
from app.platform.inbound.graph.adapters.anthropic_reminder_planner import AnthropicReminderPlanner
from app.platform.inbound.graph.adapters.anthropic_scheduling_planner import AnthropicSchedulingPlanner
from app.platform.inbound.graph.adapters.anthropic_staff_planner import AnthropicStaffPlanner
from app.platform.inbound.graph.adapters.anthropic_suggestion_generator import AnthropicSuggestionGenerator
from app.platform.inbound.graph.adapters.llm import build_chat_model
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
    async def encrypt(self, plaintext: bytes):
        raise NotImplementedError

    async def decrypt(self, secret) -> bytes:
        return b"refresh-token"


class _FakeCalendarSyncPort:
    def __init__(self) -> None:
        self.upsert_calls: list = []

    async def upsert_event(self, cred, mapping) -> CalendarSyncResult:
        self.upsert_calls.append((cred, mapping))
        return CalendarSyncResult(ok=True, google_event_id="evt-1")

    async def delete_event(self, cred, google_event_id) -> CalendarSyncResult:
        raise NotImplementedError


async def test_build_permission_service_returns_a_fresh_instance_each_call(rls_conn) -> None:
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


def test_build_scope_policy_returns_a_real_anthropic_backed_adapter() -> None:
    policy = build_scope_policy()

    assert isinstance(policy, AnthropicScopePolicy)


def test_build_intent_classifier_returns_a_real_anthropic_backed_adapter() -> None:
    classifier = build_intent_classifier()

    assert isinstance(classifier, AnthropicIntentClassifier)


def test_build_affirmation_classifier_returns_a_real_anthropic_backed_adapter() -> None:
    classifier = build_affirmation_classifier()

    assert isinstance(classifier, AnthropicAffirmationClassifier)


def test_the_three_llm_seam_builders_accept_a_shared_pre_built_chat_model() -> None:
    fast_llm = build_chat_model("fast")

    assert isinstance(build_scope_policy(fast_llm), AnthropicScopePolicy)
    assert isinstance(build_intent_classifier(fast_llm), AnthropicIntentClassifier)
    assert isinstance(build_affirmation_classifier(fast_llm), AnthropicAffirmationClassifier)


def test_build_scheduling_planner_returns_a_real_anthropic_backed_adapter() -> None:
    planner = build_scheduling_planner()

    assert isinstance(planner, AnthropicSchedulingPlanner)


def test_build_staff_planner_returns_a_real_anthropic_backed_adapter() -> None:
    planner = build_staff_planner()

    assert isinstance(planner, AnthropicStaffPlanner)


def test_build_reminder_planner_returns_a_real_anthropic_backed_adapter() -> None:
    planner = build_reminder_planner()

    assert isinstance(planner, AnthropicReminderPlanner)


def test_build_direct_response_returns_a_real_anthropic_backed_adapter() -> None:
    adapter = build_direct_response()

    assert isinstance(adapter, AnthropicDirectResponse)


def test_build_suggestion_generator_returns_a_real_anthropic_backed_adapter() -> None:
    generator = build_suggestion_generator()

    assert isinstance(generator, AnthropicSuggestionGenerator)


def test_scheduling_and_staff_planner_builders_accept_a_shared_reasoner_model() -> None:
    reasoner_llm = build_chat_model("reasoner")

    assert isinstance(build_scheduling_planner(reasoner_llm), AnthropicSchedulingPlanner)
    assert isinstance(build_staff_planner(reasoner_llm), AnthropicStaffPlanner)


def test_the_three_new_fast_tier_builders_accept_a_shared_pre_built_chat_model() -> None:
    fast_llm = build_chat_model("fast")

    assert isinstance(build_reminder_planner(fast_llm), AnthropicReminderPlanner)
    assert isinstance(build_direct_response(fast_llm), AnthropicDirectResponse)
    assert isinstance(build_suggestion_generator(fast_llm), AnthropicSuggestionGenerator)


async def test_build_get_tenant_reads_the_real_llm_daily_budget_column(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)

    tenant = await build_get_tenant(rls_conn).execute(tenant_id)

    assert tenant.id == tenant_id
    assert tenant.llm_daily_budget_tokens == 100_000  # DDL default, migration 7441c553c450


def test_build_chat_rate_limiter_returns_a_real_chat_rate_limiter(rls_conn) -> None:
    from app.platform.inbound.api.rate_limit.chat_rate_limiter import ChatRateLimiter

    limiter = build_chat_rate_limiter(rls_conn)

    assert isinstance(limiter, ChatRateLimiter)


def test_build_auth_account_rate_limiter_returns_a_real_fixed_window_limiter(db_conn) -> None:
    from app.platform.inbound.api.rate_limit.fixed_window_limiter import FixedWindowRateLimiter

    limiter = build_auth_account_rate_limiter(db_conn)

    assert isinstance(limiter, FixedWindowRateLimiter)


async def test_build_auth_account_rate_limiter_actually_persists_counts_against_real_postgres(db_conn) -> None:
    tenant_id = await seed_tenant(db_conn)
    limiter = build_auth_account_rate_limiter(db_conn)
    subject = f"{tenant_id}:acct-limiter@example.com"

    for _ in range(3):
        allowed = await limiter.check(
            dimension="auth_account", subject=subject, window_seconds=300, limit=5, tenant_id=tenant_id
        )
        assert allowed is True

    denied = await limiter.check(
        dimension="auth_account", subject=subject, window_seconds=300, limit=3, tenant_id=tenant_id
    )
    assert denied is False


def test_build_chat_rate_limiter_shares_the_same_process_wide_token_bucket_registry(rls_conn) -> None:
    first = build_chat_rate_limiter(rls_conn)
    second = build_chat_rate_limiter(rls_conn)

    assert first._token_buckets is second._token_buckets
