"""Wires adapters into use cases. The only module allowed to cross module boundaries."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

import httpx
import psycopg
from langchain_anthropic import ChatAnthropic
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.config import settings
from app.db import engine, runtime_engine
from app.modules.calendar.adapters.outbound.calendar.aes_gcm_vault import AesGcmVault
from app.modules.calendar.adapters.outbound.calendar.google_calendar_adapter import GoogleCalendarAdapter
from app.modules.calendar.adapters.outbound.postgres.calendar_credential_repository import (
    PostgresCalendarCredentialRepository,
)
from app.modules.calendar.adapters.outbound.postgres.calendar_sync_repository import PostgresCalendarSyncRepository
from app.modules.calendar.adapters.outbound.postgres.patient_email_lookup import PostgresPatientEmailLookup
from app.modules.calendar.application.ports.driven.appointment_snapshot import (
    AppointmentSnapshotPort,
    AppointmentSyncSnapshot,
)
from app.modules.calendar.application.ports.driven.calendar_credential_repository import (
    CalendarCredentialRepositoryPort,
)
from app.modules.calendar.application.ports.driven.calendar_sync import CalendarSyncPort
from app.modules.calendar.application.ports.driven.credential_vault import CredentialVaultPort
from app.modules.calendar.application.use_cases.connect_patient_calendar import ConnectPatientCalendar
from app.modules.calendar.application.use_cases.sync_appointment_to_calendar import SyncAppointmentToCalendar
from app.modules.governance.audit.adapters.outbound.postgres.audit_log import PostgresAuditLog
from app.modules.governance.audit.application.ports.driven.audit_log import AuditLogPort
from app.modules.governance.audit.domain.audit_entry import AuditEntry
from app.modules.governance.consent.adapters.outbound.postgres.consent_registry import PostgresConsentRegistry
from app.modules.governance.consent.application.use_cases.check_consent import CheckConsent
from app.modules.governance.rbac.adapters.outbound.rbac.action_catalog import seed_action_catalog
from app.modules.governance.rbac.adapters.outbound.rbac.default_role_permissions import (
    seed_default_role_permissions,
)
from app.modules.governance.rbac.adapters.outbound.rbac.permission_service import PermissionService
from app.modules.governance.rbac.application.use_cases.authorize_action import AuthorizeAction
from app.modules.governance.scope.adapters.outbound.anthropic.anthropic_scope_policy import AnthropicScopePolicy
from app.modules.governance.scope.domain.scope_policy import ClinicalScopePolicy
from app.modules.identity.adapters.outbound.auth.supabase_auth_adapter import SupabaseAuthAdapter
from app.modules.identity.adapters.outbound.postgres.session_store import PostgresSessionStore
from app.modules.identity.adapters.outbound.postgres.user_directory import PostgresUserDirectory
from app.modules.identity.adapters.outbound.tokens.jwt_access_token_issuer import JwtAccessTokenIssuer
from app.modules.identity.adapters.outbound.tokens.jwt_access_token_verifier import JwtAccessTokenVerifier
from app.modules.identity.adapters.outbound.tokens.secure_secret_generator import SecureSecretGenerator
from app.modules.identity.adapters.outbound.tokens.ttl_rotation_replay_cache import TTLRotationReplayCache
from app.modules.identity.application.ports.driven.user_directory import UserDirectoryPort
from app.modules.identity.application.use_cases.complete_password_reset import CompletePasswordReset
from app.modules.identity.application.use_cases.login import Login
from app.modules.identity.application.use_cases.logout import Logout
from app.modules.identity.application.use_cases.provision_staff_identity import ProvisionStaffIdentity
from app.modules.identity.application.use_cases.refresh_token import RefreshToken
from app.modules.identity.application.use_cases.request_password_reset import RequestPasswordReset
from app.modules.scheduling.adapters.outbound.postgres.availability_repository import PostgresAvailabilityRepository
from app.modules.scheduling.adapters.outbound.postgres.scheduling_repository import PostgresSchedulingRepository
from app.modules.scheduling.application.ports.driven.scheduling_repository import SchedulingRepositoryPort
from app.modules.scheduling.application.ports.driven.staff_status_port import StaffStatusPort
from app.modules.scheduling.application.use_cases.cancel_appointment import CancelAppointment
from app.modules.scheduling.application.use_cases.reschedule_appointment import RescheduleAppointment
from app.modules.scheduling.application.use_cases.schedule_appointment import ScheduleAppointment
from app.modules.scheduling.application.use_cases.send_reminder import SendReminder
from app.modules.staff.adapters.outbound.postgres.shift_repository import PostgresShiftRepository
from app.modules.staff.adapters.outbound.postgres.staff_repository import PostgresStaffRepository
from app.modules.staff.application.use_cases.create_shift import CreateShift
from app.modules.staff.application.use_cases.deactivate_staff import DeactivateStaff
from app.modules.staff.application.use_cases.edit_shift import EditShift
from app.modules.staff.application.use_cases.register_staff import RegisterStaff
from app.modules.staff.domain.staff_policy import StaffPolicy
from app.modules.tenancy.adapters.outbound.postgres.tenant_repository import PostgresTenantRepository
from app.modules.tenancy.application.use_cases.get_tenant import GetTenant
from app.platform.inbound.api.access_control.role_scope import scoped_as_admin, scoped_as_patient
from app.platform.inbound.api.access_control.runtime_session import EngineRuntimeSession
from app.platform.inbound.api.audit_safety import record_audit_best_effort
from app.platform.inbound.api.rate_limit.adapters.postgres_rate_counter_store import PostgresRateCounterStore
from app.platform.inbound.api.rate_limit.chat_rate_limiter import ChatRateLimiter
from app.platform.inbound.api.rate_limit.fixed_window_limiter import FixedWindowRateLimiter
from app.platform.inbound.api.rate_limit.llm_budget_guard import LlmBudgetGuard
from app.platform.inbound.api.rate_limit.token_bucket import TokenBucketRegistry
from app.platform.inbound.graph.adapters.anthropic_affirmation_classifier import AnthropicAffirmationClassifier
from app.platform.inbound.graph.adapters.anthropic_direct_response import AnthropicDirectResponse
from app.platform.inbound.graph.adapters.anthropic_intent_classifier import AnthropicIntentClassifier
from app.platform.inbound.graph.adapters.anthropic_reminder_planner import AnthropicReminderPlanner
from app.platform.inbound.graph.adapters.anthropic_scheduling_planner import AnthropicSchedulingPlanner
from app.platform.inbound.graph.adapters.anthropic_staff_planner import AnthropicStaffPlanner
from app.platform.inbound.graph.adapters.anthropic_suggestion_generator import AnthropicSuggestionGenerator
from app.platform.inbound.graph.adapters.llm import build_chat_model
from app.platform.inbound.graph.ports.affirmation_classifier import AffirmationClassifierPort
from app.platform.inbound.graph.ports.direct_response import DirectResponsePort
from app.platform.inbound.graph.ports.intent_classifier import IntentClassifierPort
from app.platform.inbound.graph.ports.reminder_planner import ReminderPlannerPort
from app.platform.inbound.graph.ports.scheduling_planner import SchedulingPlannerPort
from app.platform.inbound.graph.ports.staff_planner import StaffPlannerPort
from app.platform.inbound.graph.ports.suggestion_generator import SuggestionGeneratorPort
from app.platform.outbound.channel.console_channel import ConsoleReminderChannel
from app.shared_kernel.clock import ClockPort, SystemClock


@asynccontextmanager
async def open_runtime_connection() -> AsyncIterator[AsyncConnection]:
    async with runtime_engine.connect() as conn:
        async with conn.begin():
            yield conn


@asynccontextmanager
async def open_elevated_connection() -> AsyncIterator[AsyncConnection]:
    async with engine.connect() as conn:
        async with conn.begin():
            yield conn


def _checkpointer_psycopg_dsn() -> str:
    return settings.runtime_database_url.replace("postgresql+asyncpg://", "postgresql://")


@asynccontextmanager
async def open_checkpointer_connection(tenant_id: str) -> AsyncIterator[psycopg.AsyncConnection]:
    async with await psycopg.AsyncConnection.connect(_checkpointer_psycopg_dsn(), autocommit=True) as conn:
        async with conn.cursor() as cur:
            await cur.execute(f"SET app.tenant_id = '{tenant_id}'")
        yield conn


def build_permission_service(conn: AsyncConnection) -> PermissionService:
    return PermissionService(conn)


class PostgresStaffStatusAdapter:
    def __init__(self, conn: AsyncConnection) -> None:
        self._staff_repository = PostgresStaffRepository(conn)

    async def is_assignable(self, tenant_id: str, professional_id: str) -> bool:
        staff_member = await self._staff_repository.find_by_professional_id(tenant_id, professional_id)
        if staff_member is None:
            return False
        return StaffPolicy.is_assignable(staff_member)


class PostgresAppointmentSnapshotAdapter:
    def __init__(self, conn: AsyncConnection) -> None:
        self._scheduling_repository = PostgresSchedulingRepository(conn)

    async def get_snapshot(self, tenant_id: str, appointment_id: str) -> AppointmentSyncSnapshot | None:
        appointment = await self._scheduling_repository.get_appointment(tenant_id, appointment_id)
        if appointment is None:
            return None
        return AppointmentSyncSnapshot(
            patient_id=appointment.patient_id,
            starts_at=appointment.starts_at,
            ends_at=appointment.ends_at,
            site_id=appointment.site_id,
        )


class RoleScopedCalendarCredentialRepository:
    def __init__(self, inner: CalendarCredentialRepositoryPort, conn: AsyncConnection, *, base_role: str) -> None:
        self._inner = inner
        self._conn = conn
        self._base_role = base_role

    async def get(self, tenant_id: str, patient_id: str):
        async with scoped_as_patient(self._conn, patient_id=patient_id, restore_role=self._base_role):
            return await self._inner.get(tenant_id, patient_id)

    async def save(self, tenant_id: str, patient_id: str, secret, *, scope: str):
        async with scoped_as_patient(self._conn, patient_id=patient_id, restore_role=self._base_role):
            return await self._inner.save(tenant_id, patient_id, secret, scope=scope)

    async def revoke(self, tenant_id: str, patient_id: str) -> None:
        async with scoped_as_patient(self._conn, patient_id=patient_id, restore_role=self._base_role):
            await self._inner.revoke(tenant_id, patient_id)


def build_sync_appointment_to_calendar(
    conn: AsyncConnection,
    *,
    base_role: str,
    calendar_sync_port: CalendarSyncPort,
    credential_vault: CredentialVaultPort,
    audit_log: AuditLogPort | None = None,
) -> SyncAppointmentToCalendar:
    credential_repository = RoleScopedCalendarCredentialRepository(
        PostgresCalendarCredentialRepository(conn), conn, base_role=base_role
    )
    calendar_sync_repository = PostgresCalendarSyncRepository(conn)
    return SyncAppointmentToCalendar(
        credential_repository,
        credential_vault,
        calendar_sync_repository,
        calendar_sync_port,
        audit_log or PostgresAuditLog(conn),
    )


async def bootstrap_rbac_catalog_and_grants(conn: AsyncConnection) -> None:
    await seed_action_catalog(conn)
    tenant_rows = await conn.execute(text("SELECT id FROM tenants"))
    tenant_ids = [str(row[0]) for row in tenant_rows]
    for tenant_id in tenant_ids:
        await conn.execute(text(f"SET LOCAL app.tenant_id = '{tenant_id}'"))
        await conn.execute(text("SET LOCAL app.role = 'admin'"))
        await seed_default_role_permissions(conn, tenant_id)


def build_authorize_action(conn: AsyncConnection) -> AuthorizeAction:
    return AuthorizeAction(build_permission_service(conn))


def build_runtime_session() -> EngineRuntimeSession:
    return EngineRuntimeSession(runtime_engine)


def build_access_token_verifier() -> JwtAccessTokenVerifier:
    return JwtAccessTokenVerifier(secret=settings.identity_access_token_secret)


def build_access_token_issuer(clock: ClockPort | None = None) -> JwtAccessTokenIssuer:
    return JwtAccessTokenIssuer(secret=settings.identity_access_token_secret, clock=clock or SystemClock())


# Process-wide singleton: rotation grace cache must be shared across requests
# on this process (no cross-instance replication in MVP).
_rotation_replay_cache = TTLRotationReplayCache()


def build_login(conn: AsyncConnection, *, http_client: httpx.AsyncClient) -> Login:
    clock = SystemClock()
    return Login(
        SupabaseAuthAdapter(
            base_url=settings.supabase_url or "", api_key=settings.supabase_anon_key or "", http_client=http_client
        ),
        PostgresUserDirectory(conn),
        PostgresSessionStore(conn),
        build_access_token_issuer(clock),
        SecureSecretGenerator(),
        PostgresAuditLog(conn),
        clock,
        access_token_ttl=timedelta(minutes=settings.identity_access_token_ttl_minutes),
        refresh_token_ttl=timedelta(days=settings.identity_refresh_token_ttl_days),
    )


def build_refresh_token(conn: AsyncConnection) -> RefreshToken:
    clock = SystemClock()
    return RefreshToken(
        PostgresSessionStore(conn),
        PostgresUserDirectory(conn),
        build_access_token_issuer(clock),
        SecureSecretGenerator(),
        _rotation_replay_cache,
        clock,
        access_token_ttl=timedelta(minutes=settings.identity_access_token_ttl_minutes),
        refresh_token_ttl=timedelta(days=settings.identity_refresh_token_ttl_days),
        grace_period=timedelta(seconds=settings.identity_refresh_grace_period_seconds),
    )


def build_request_password_reset(http_client: httpx.AsyncClient) -> RequestPasswordReset:
    return RequestPasswordReset(
        SupabaseAuthAdapter(
            base_url=settings.supabase_url or "", api_key=settings.supabase_anon_key or "", http_client=http_client
        ),
        redirect_url=settings.frontend_base_url,
    )


class ElevatedIsolatedAuditLog:
    async def record_best_effort(self, entry: AuditEntry) -> None:
        async with open_elevated_connection() as conn:
            await record_audit_best_effort(PostgresAuditLog(conn), entry)


def build_complete_password_reset(conn: AsyncConnection, *, http_client: httpx.AsyncClient) -> CompletePasswordReset:
    clock = SystemClock()
    return CompletePasswordReset(
        SupabaseAuthAdapter(
            base_url=settings.supabase_url or "", api_key=settings.supabase_anon_key or "", http_client=http_client
        ),
        PostgresUserDirectory(conn),
        PostgresSessionStore(conn),
        build_access_token_issuer(clock),
        SecureSecretGenerator(),
        ElevatedIsolatedAuditLog(),
        clock,
        access_token_ttl=timedelta(minutes=settings.identity_access_token_ttl_minutes),
        refresh_token_ttl=timedelta(days=settings.identity_refresh_token_ttl_days),
    )


class AdminElevatedUserDirectory:
    def __init__(self, inner: UserDirectoryPort, conn: AsyncConnection, *, restore_role: str) -> None:
        self._inner = inner
        self._conn = conn
        self._restore_role = restore_role

    async def find_by_email(self, tenant_id: str, email: str):
        return await self._inner.find_by_email(tenant_id, email)

    async def find_by_auth_subject(self, tenant_id: str, auth_subject: str):
        return await self._inner.find_by_auth_subject(tenant_id, auth_subject)

    async def get_by_id(self, tenant_id: str, user_id: str):
        return await self._inner.get_by_id(tenant_id, user_id)

    async def link_auth_subject(self, tenant_id: str, user_id: str, *, auth_subject: str, email_verified: bool):
        return await self._inner.link_auth_subject(
            tenant_id, user_id, auth_subject=auth_subject, email_verified=email_verified
        )

    async def provision_patient_user(
        self, tenant_id: str, *, site_id: str, email: str, auth_subject: str, email_verified: bool
    ):
        return await self._inner.provision_patient_user(
            tenant_id, site_id=site_id, email=email, auth_subject=auth_subject, email_verified=email_verified
        )

    async def provision_staff_user(
        self,
        tenant_id: str,
        *,
        site_id: str,
        role: str,
        email: str,
        auth_subject: str,
        email_verified: bool,
        professional_id: str | None = None,
    ):
        async with scoped_as_admin(self._conn, restore_role=self._restore_role):
            return await self._inner.provision_staff_user(
                tenant_id,
                site_id=site_id,
                role=role,
                email=email,
                auth_subject=auth_subject,
                email_verified=email_verified,
                professional_id=professional_id,
            )


def build_provision_staff_identity(
    conn: AsyncConnection, *, http_client: httpx.AsyncClient, restore_role: str
) -> ProvisionStaffIdentity:
    return ProvisionStaffIdentity(
        SupabaseAuthAdapter(
            base_url=settings.supabase_url or "",
            api_key=settings.supabase_anon_key or "",
            http_client=http_client,
            service_role_key=settings.supabase_service_role_key or "",
        ),
        AdminElevatedUserDirectory(PostgresUserDirectory(conn), conn, restore_role=restore_role),
        PostgresAuditLog(conn),
        invite_redirect_url=f"{settings.frontend_base_url}/staff/login",
    )


def build_auth_account_rate_limiter(conn: AsyncConnection) -> FixedWindowRateLimiter:
    return FixedWindowRateLimiter(PostgresRateCounterStore(conn), clock=SystemClock())


def build_logout(conn: AsyncConnection) -> Logout:
    return Logout(PostgresSessionStore(conn), SystemClock())


def build_check_consent(conn: AsyncConnection) -> CheckConsent:
    return CheckConsent(PostgresConsentRegistry(conn))


def build_scheduling_repository(conn: AsyncConnection) -> SchedulingRepositoryPort:
    return PostgresSchedulingRepository(conn)


def build_schedule_appointment(conn: AsyncConnection) -> ScheduleAppointment:
    """`conn` MUST be an `open_runtime_connection()` connection with the
    caller's `app.*` GUCs already set (RLS-scoped, RBAC-gated)."""
    return ScheduleAppointment(
        build_authorize_action(conn),
        PostgresAvailabilityRepository(conn),
        PostgresSchedulingRepository(conn),
        PostgresAuditLog(conn),
        PostgresStaffStatusAdapter(conn),
    )


def build_reschedule_appointment(conn: AsyncConnection) -> RescheduleAppointment:
    return RescheduleAppointment(
        build_authorize_action(conn),
        PostgresAvailabilityRepository(conn),
        PostgresSchedulingRepository(conn),
        PostgresAuditLog(conn),
        PostgresStaffStatusAdapter(conn),
    )


def build_cancel_appointment(conn: AsyncConnection) -> CancelAppointment:
    return CancelAppointment(
        build_authorize_action(conn),
        PostgresAvailabilityRepository(conn),
        PostgresSchedulingRepository(conn),
        PostgresAuditLog(conn),
    )


def build_send_reminder(conn: AsyncConnection) -> SendReminder:
    return SendReminder(
        build_authorize_action(conn),
        PostgresSchedulingRepository(conn),
        ConsoleReminderChannel(),
        PostgresAuditLog(conn),
    )


def build_connect_patient_calendar(conn: AsyncConnection) -> ConnectPatientCalendar:
    return ConnectPatientCalendar(
        build_authorize_action(conn),
        PostgresPatientEmailLookup(conn),
        AesGcmVault(),
        PostgresCalendarCredentialRepository(conn),
        PostgresAuditLog(conn),
    )


def build_google_calendar_adapter(http_client: httpx.AsyncClient) -> GoogleCalendarAdapter:
    return GoogleCalendarAdapter(
        client_id=settings.calendar_google_client_id,
        client_secret=settings.calendar_google_client_secret,
        http_client=http_client,
    )


def build_register_staff(conn: AsyncConnection) -> RegisterStaff:
    return RegisterStaff(build_authorize_action(conn), PostgresStaffRepository(conn), PostgresAuditLog(conn))


def build_deactivate_staff(conn: AsyncConnection) -> DeactivateStaff:
    return DeactivateStaff(build_authorize_action(conn), PostgresStaffRepository(conn), PostgresAuditLog(conn))


def build_create_shift(conn: AsyncConnection) -> CreateShift:
    return CreateShift(
        build_authorize_action(conn),
        PostgresStaffRepository(conn),
        PostgresShiftRepository(conn),
        PostgresAuditLog(conn),
    )


def build_edit_shift(conn: AsyncConnection) -> EditShift:
    return EditShift(build_authorize_action(conn), PostgresShiftRepository(conn), PostgresAuditLog(conn))


def build_scope_policy(llm: ChatAnthropic | None = None) -> ClinicalScopePolicy:
    return AnthropicScopePolicy(llm or build_chat_model("fast"))


def build_intent_classifier(llm: ChatAnthropic | None = None) -> IntentClassifierPort:
    # Same shared-`llm` convention as `build_scope_policy` above.
    return AnthropicIntentClassifier(llm or build_chat_model("fast"))


def build_affirmation_classifier(llm: ChatAnthropic | None = None) -> AffirmationClassifierPort:
    # Same shared-`llm` convention as `build_scope_policy` above.
    return AnthropicAffirmationClassifier(llm or build_chat_model("fast"))


def build_scheduling_planner(llm: ChatAnthropic | None = None) -> SchedulingPlannerPort:
    return AnthropicSchedulingPlanner(llm or build_chat_model("reasoner"))


def build_staff_planner(llm: ChatAnthropic | None = None) -> StaffPlannerPort:
    return AnthropicStaffPlanner(llm or build_chat_model("reasoner"))


def build_reminder_planner(llm: ChatAnthropic | None = None) -> ReminderPlannerPort:
    return AnthropicReminderPlanner(llm or build_chat_model("fast"))


def build_direct_response(llm: ChatAnthropic | None = None) -> DirectResponsePort:
    return AnthropicDirectResponse(llm or build_chat_model("fast"))


def build_suggestion_generator(llm: ChatAnthropic | None = None) -> SuggestionGeneratorPort:
    return AnthropicSuggestionGenerator(llm or build_chat_model("fast"))


def build_get_tenant(conn: AsyncConnection) -> GetTenant:
    return GetTenant(PostgresTenantRepository(conn))


class _ElevatedRateCounterStore:
    async def increment(self, *, dimension, subject, window_start, by=1, tenant_id=None) -> int:
        async with open_elevated_connection() as conn:
            return await PostgresRateCounterStore(conn).increment(
                dimension=dimension, subject=subject, window_start=window_start, by=by, tenant_id=tenant_id
            )

    async def peek(self, *, dimension, subject, window_start, tenant_id=None) -> int:
        async with open_elevated_connection() as conn:
            return await PostgresRateCounterStore(conn).peek(
                dimension=dimension, subject=subject, window_start=window_start, tenant_id=tenant_id
            )


# Process-wide singleton: per-instance token bucket must be shared across requests.
_chat_token_buckets = TokenBucketRegistry(
    capacity=settings.chat_rate_limit_capacity,
    refill_per_second=settings.chat_rate_limit_refill_per_second,
    clock=SystemClock(),
)


def build_chat_rate_limiter(conn: AsyncConnection) -> ChatRateLimiter:
    return ChatRateLimiter(
        _chat_token_buckets,
        LlmBudgetGuard(_ElevatedRateCounterStore(), clock=SystemClock(), record_audit=PostgresAuditLog(conn)),
    )


__all__ = [
    "AdminElevatedUserDirectory",
    "AppointmentSnapshotPort",
    "PostgresAppointmentSnapshotAdapter",
    "PostgresStaffStatusAdapter",
    "RoleScopedCalendarCredentialRepository",
    "StaffStatusPort",
    "bootstrap_rbac_catalog_and_grants",
    "build_access_token_issuer",
    "build_access_token_verifier",
    "build_affirmation_classifier",
    "build_auth_account_rate_limiter",
    "build_authorize_action",
    "build_cancel_appointment",
    "build_chat_rate_limiter",
    "build_check_consent",
    "build_complete_password_reset",
    "build_connect_patient_calendar",
    "build_create_shift",
    "build_deactivate_staff",
    "build_direct_response",
    "build_edit_shift",
    "build_get_tenant",
    "build_google_calendar_adapter",
    "build_intent_classifier",
    "build_login",
    "build_provision_staff_identity",
    "build_register_staff",
    "build_logout",
    "build_permission_service",
    "build_refresh_token",
    "build_reminder_planner",
    "build_request_password_reset",
    "build_reschedule_appointment",
    "build_runtime_session",
    "build_schedule_appointment",
    "build_scheduling_planner",
    "build_scheduling_repository",
    "build_scope_policy",
    "build_send_reminder",
    "build_staff_planner",
    "build_suggestion_generator",
    "build_sync_appointment_to_calendar",
    "open_checkpointer_connection",
    "open_elevated_connection",
    "open_runtime_connection",
]
