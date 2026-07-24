"""Composition root (design.md §2.5, tasks.md task 10.2): the ONE module
allowed to import every business module and platform layer at once and wire
concrete adapters into use cases. No other module may reach across module
boundaries -- see `backend/AGENTS.md` and `import-linter`'s three contracts
in `pyproject.toml`, none of which constrain this module (it sits outside
the `platform`/`modules` layer trees `app.composition_root` is a sibling
of, exactly as design.md §2.5 describes: "Un unico composition_root.py es
el unico lugar que conoce todos los modulos a la vez; nada mas los
conecta.").

This module does NOT build the FastAPI app itself or mount routers -- that
is `app/main.py` (tasks.md task 10.1). What lives here are the wiring
PRIMITIVES/FACTORY FUNCTIONS `app/main.py` and its routers use, closing:

**Session 1 (task 10.2, four specific previously-flagged composition-root
gaps -- see below for the original four)**, plus:

**Session 2 (task 10.1/10.2 finish, this batch):** `build_*` factory
functions for every use case task 10.1's routers need --
`Login`/`RefreshToken`/`Logout` (identity), `ScheduleAppointment`/
`RescheduleAppointment`/`CancelAppointment`/`SendReminder` (scheduling),
`ConnectPatientCalendar` (calendar) -- plus `open_elevated_connection()`
(the pre-auth `app.db.engine` counterpart to `open_runtime_connection()`,
needed by `Login`/`RefreshToken`/the access-control middleware's live-actor
resolution, all of which run BEFORE any `app.*` GUC/`TenantContext` exists)
and `build_runtime_session()` (wires `AccessControlMiddleware`'s
`RuntimeSessionPort` dependency to the real `EngineRuntimeSession`).
`ConsoleReminderChannel` (the concrete `ReminderChannelPort` MVP adapter
`reminder_channel.py`'s own docstring flagged as missing) lives at
`app/platform/outbound/channel/console_channel.py` per design.md §2.5's
folder layout, not here -- this module only wires it in.

**Session 3 (tasks.md task 11.5, PR 11 batch 3):** `build_register_staff`/
`build_deactivate_staff`/`build_create_shift`/`build_edit_shift` -- the four
staff use cases had NO composition-root wiring anywhere before this batch
(confirmed via `grep "^def build_" app/composition_root.py` per this
task's own instruction) -- `persist_and_audit`'s (graph/nodes/
persist_and_audit.py) dispatch table is their first real caller.

The original four gaps this module closed in task 10.2's first session:

1. **`runtime_engine`, never `engine`, for request-scoped work**
   (`app.db`'s own module docstring) -- `open_runtime_connection()` below is
   the one sanctioned way to obtain a request-scoped, RLS-enforced
   connection.
2. **A fresh `PermissionService` per request, never a singleton**
   (`PermissionService`'s own module docstring, ADR-16/design.md §5.6) --
   `build_permission_service()` is a plain constructor call, deliberately
   NOT `@lru_cache`-wrapped or memoized at module scope. See
   `test_composition_root.py::test_build_permission_service_returns_a_fresh_instance_every_call`.
3. **The real `StaffStatusPort`/`AppointmentSnapshotPort` adapters**
   (tasks.md tasks 8.4/9.5's deliberately-open seams, `UnwiredStaffStatusAdapter`/
   `UnwiredAppointmentSnapshotAdapter`) -- `PostgresStaffStatusAdapter` and
   `PostgresAppointmentSnapshotAdapter` below are the option-1 resolution
   both seams' docstrings recommended: a composition-root-level adapter
   built from the OTHER module's own repository/port, never a raw
   cross-module SQL query and never a cross-module Python import from
   inside `scheduling`/`calendar` themselves.
4. **`SyncAppointmentToCalendar`'s dual-role RLS requirement**
   (`sync_appointment_to_calendar.py`'s and
   `calendar_credential_repository.py`'s own flagged gap) --
   `RoleScopedCalendarCredentialRepository` + `build_sync_appointment_to_calendar()`
   resolve it using `role_scope.py`'s `scoped_as_patient` (the purpose-built
   mechanism for exactly this case), re-scoping the connection to
   `app.role='patient'` ONLY for the credential read, restoring the
   caller-supplied staff `base_role` immediately after (even on error) so
   `calendar_sync`'s staff-only policy is satisfied for every other query
   this use case makes on the same connection.

Also closes tasks.md task 3.6's own forward pointer: `bootstrap_rbac_catalog_and_grants()`
actually calls `seed_action_catalog`/`seed_default_role_permissions` (task
3.6, explicitly PLACEHOLDER/dev-only per that module's docstrings) so
`AuthorizeAction` is not deny-by-default-for-lack-of-seed-data in a running
instance. Wired into `app/main.py`'s lifespan hook as of this session (see
that module) -- called exactly once, against `open_runtime_connection()`,
before the app starts serving traffic.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

import httpx
import psycopg
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
from app.modules.governance.rbac.adapters.outbound.rbac.action_catalog import seed_action_catalog
from app.modules.governance.rbac.adapters.outbound.rbac.default_role_permissions import (
    seed_default_role_permissions,
)
from app.modules.governance.rbac.adapters.outbound.rbac.permission_service import PermissionService
from app.modules.governance.rbac.application.use_cases.authorize_action import AuthorizeAction
from app.modules.identity.adapters.outbound.auth.supabase_auth_adapter import SupabaseAuthAdapter
from app.modules.identity.adapters.outbound.postgres.session_store import PostgresSessionStore
from app.modules.identity.adapters.outbound.postgres.user_directory import PostgresUserDirectory
from app.modules.identity.adapters.outbound.tokens.jwt_access_token_issuer import JwtAccessTokenIssuer
from app.modules.identity.adapters.outbound.tokens.jwt_access_token_verifier import JwtAccessTokenVerifier
from app.modules.identity.adapters.outbound.tokens.secure_secret_generator import SecureSecretGenerator
from app.modules.identity.adapters.outbound.tokens.ttl_rotation_replay_cache import TTLRotationReplayCache
from app.modules.identity.application.use_cases.login import Login
from app.modules.identity.application.use_cases.logout import Logout
from app.modules.identity.application.use_cases.refresh_token import RefreshToken
from app.modules.scheduling.adapters.outbound.postgres.availability_repository import PostgresAvailabilityRepository
from app.modules.scheduling.adapters.outbound.postgres.scheduling_repository import PostgresSchedulingRepository
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
from app.platform.inbound.api.access_control.role_scope import scoped_as_patient
from app.platform.inbound.api.access_control.runtime_session import EngineRuntimeSession
from app.platform.outbound.channel.console_channel import ConsoleReminderChannel
from app.shared_kernel.clock import ClockPort, SystemClock


@asynccontextmanager
async def open_runtime_connection() -> AsyncIterator[AsyncConnection]:
    """Opens ONE connection against `app.db.runtime_engine` (`app_runtime`,
    RLS-enforced), inside its own transaction, committed on a clean exit and
    rolled back on any exception. This is the sanctioned way for a
    request-scoped dependency (`app/main.py`'s lifespan hook) or a
    background job (the calendar retry job, tasks.md task 9.5) to obtain a
    connection -- never `app.db.engine` (see that module's docstring for
    why: it connects as the `app_user` superuser and unconditionally
    bypasses RLS)."""
    async with runtime_engine.connect() as conn:
        async with conn.begin():
            yield conn


@asynccontextmanager
async def open_elevated_connection() -> AsyncIterator[AsyncConnection]:
    """Opens ONE connection against `app.db.engine` (`app_user`, elevated,
    BYPASSES RLS), inside its own transaction. This is the ONLY sanctioned
    way to obtain the pre-`app.*`-GUC connection `Login`/`RefreshToken`
    (identity's own docstrings: "no `app.*` GUC exists yet when `Login`
    runs") and `PostgresLiveActorResolver`/`PostgresRateCounterStore`
    (access-control middleware's live-actor resolution and pre-login IP
    rate limiting, both of which run BEFORE any session context exists)
    require -- never use this for a request-scoped BUSINESS query once a
    `TenantContext` exists; `open_runtime_connection()` above is for that."""
    async with engine.connect() as conn:
        async with conn.begin():
            yield conn


def _checkpointer_psycopg_dsn() -> str:
    """`langgraph-checkpoint-postgres` requires a `psycopg` connection, not
    `asyncpg` -- a genuinely separate physical connection from every other
    `AsyncConnection` in this module (all `asyncpg`, per `app.db`'s own
    docstring). Mirrors migration `043b5dd9768e`'s own `_psycopg_dsn()`
    (same driver-suffix-stripping reason), but built from
    `runtime_database_url` (`app_runtime`, RLS-enforced), never
    `database_url` (`app_user`, superuser, unconditionally bypasses RLS --
    `checkpoints`/`checkpoint_writes`/`checkpoint_blobs` genuinely need
    their `thread_id`-tenant-prefix RLS policy enforced, the same as every
    other tenant-scoped table this module wires)."""
    return settings.runtime_database_url.replace("postgresql+asyncpg://", "postgresql://")


@asynccontextmanager
async def open_checkpointer_connection(tenant_id: str) -> AsyncIterator[psycopg.AsyncConnection]:
    """Opens ONE dedicated, per-request `psycopg` connection for
    `AsyncPostgresSaver` (`langgraph.checkpoint.postgres.aio`), with
    `app.tenant_id` set for the connection's lifetime -- see
    `graph/build_graph.py`'s own module docstring for the FLAGGED gap this
    closes only partially: `checkpoints`/`checkpoint_writes`/
    `checkpoint_blobs`' RLS policy (migration `043b5dd9768e`) filters on
    `current_setting('app.tenant_id')`, and nothing inside
    `langgraph-checkpoint-postgres` itself sets that GUC -- this function is
    the one sanctioned place that does, for whichever ONE tenant this
    specific chat request belongs to (task 11.7's chat endpoint is this
    function's only caller today).

    `autocommit=True` (no explicit transaction wrapping this connection's
    lifetime) -- unlike `open_runtime_connection()`/`open_elevated_
    connection()` above, `AsyncPostgresSaver` manages its OWN multi-statement
    writes internally per checkpoint `put`/`put_writes` call; wrapping the
    WHOLE connection in one long-lived transaction this function does not
    control the boundaries of would risk holding a transaction open for the
    entire duration of a chat turn (including any LLM latency) for no
    benefit `SET LOCAL` would otherwise provide -- there is no OTHER write on
    this connection that needs its GUC-scoping to be transaction-scoped
    (`SET` without `LOCAL`, session-scoped, is deliberately used here for
    exactly that reason -- see the plain `SET` below, not `SET LOCAL`)."""
    async with await psycopg.AsyncConnection.connect(_checkpointer_psycopg_dsn(), autocommit=True) as conn:
        async with conn.cursor() as cur:
            await cur.execute(f"SET app.tenant_id = '{tenant_id}'")
        yield conn


def build_permission_service(conn: AsyncConnection) -> PermissionService:
    """Constructs a FRESH `PermissionService` bound to `conn`. Callers MUST
    invoke this once per request (or per background-job connection) --
    NEVER cache/memoize the returned instance across requests. See
    `PermissionService`'s own module docstring (ADR-16, design.md §5.6):
    a cross-request cache would resurrect the exact
    stale-`allowed`-after-revoke privilege-escalation window that design
    explicitly rules out. This function is deliberately a plain
    constructor call with no `@lru_cache`/module-level singleton anywhere
    near it -- that absence is the point, not an oversight."""
    return PermissionService(conn)


class PostgresStaffStatusAdapter:
    """Real `StaffStatusPort` (scheduling's own port,
    `application/ports/driven/staff_status_port.py`) implementation,
    resolving tasks.md task 8.4's deliberately-open
    `UnwiredStaffStatusAdapter` seam via option 1 that seam's own docstring
    recommended: a composition-root-level adapter built from `staff`'s own
    `PostgresStaffRepository.find_by_professional_id` (added specifically
    for this, tasks.md task 10.2) -- never a raw cross-module SQL query and
    never a Python import of `app.modules.staff` from inside
    `app.modules.scheduling` itself.

    Duck-types `StaffStatusPort` -- matches this codebase's convention of
    adapters never inheriting their Protocol."""

    def __init__(self, conn: AsyncConnection) -> None:
        self._staff_repository = PostgresStaffRepository(conn)

    async def is_assignable(self, tenant_id: str, professional_id: str) -> bool:
        staff_member = await self._staff_repository.find_by_professional_id(tenant_id, professional_id)
        if staff_member is None:
            return False
        return StaffPolicy.is_assignable(staff_member)


class PostgresAppointmentSnapshotAdapter:
    """Real `AppointmentSnapshotPort` (calendar's own port,
    `application/ports/driven/appointment_snapshot.py`) implementation,
    resolving tasks.md task 9.5's deliberately-open
    `UnwiredAppointmentSnapshotAdapter` seam the same way
    `PostgresStaffStatusAdapter` above resolves task 8.4's -- a
    composition-root-level adapter built from `scheduling`'s own
    `PostgresSchedulingRepository.get_appointment`, never a cross-module
    import or raw SQL against `appointments` from inside
    `app.modules.calendar`."""

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
    """Wraps a `CalendarCredentialRepositoryPort` so every method call
    temporarily re-scopes the SHARED connection to `app.role='patient'`
    (`calendar_credentials`' only RLS policy, `calendar_credentials_self`)
    for the duration of that one call, restoring `base_role` immediately
    after -- even on error, via `role_scope.py`'s `scoped_as_patient`. This
    is the composition-root-level resolution `sync_appointment_to_calendar.py`'s
    and `calendar_credential_repository.py`'s module docstrings both flag
    as a real, load-bearing gap: `SyncAppointmentToCalendar` reads
    `calendar_credentials` (patient-only policy) and writes `calendar_sync`
    (staff-only policy, `calendar_sync_staff`) on the SAME connection in one
    logical flow, and no single `app.role` value satisfies both.

    `base_role` MUST already satisfy `calendar_sync_staff`
    (`reception`/`professional`/`admin`) -- this wrapper only ever
    temporarily narrows to `'patient'`, it never widens beyond whatever
    `base_role` the caller supplies, and it never needs to know about
    `calendar_sync` itself (that table's writes happen on the connection's
    unwrapped base role, outside this wrapper, via a plain
    `PostgresCalendarSyncRepository`)."""

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
    """Wires a fully-real `SyncAppointmentToCalendar` for one connection,
    resolving its dual-role RLS requirement via
    `RoleScopedCalendarCredentialRepository` above.

    `base_role` MUST be a `calendar_sync_staff`-satisfying role
    (`reception`/`professional`/`admin`) and the connection's `app.*` GUCs
    (`tenant_id`/`site_id`/`role=base_role`) MUST already be set for it
    BEFORE this use case's `execute()` runs -- this use case is invoked
    post-commit, best-effort (design.md §7.2), independent of whichever
    role originally authored the appointment mutation (a PATIENT
    self-scheduling through the chat/web flow included) -- callers with a
    patient actor MUST resolve a designated staff `base_role` for this
    background sync flow themselves (not built here: task 10.1's future
    orchestrator/graph `calendar_sync` node, or the retry job, own that
    decision) and MUST NOT ever pass `'patient'` as `base_role` -- this
    function narrows to `'patient'` only transiently, inside
    `RoleScopedCalendarCredentialRepository`, for the credential read
    alone."""
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
    """Closes tasks.md task 3.6's own forward pointer: actually CALLS
    `seed_action_catalog` (global catalog, always) and
    `seed_default_role_permissions` (tenant-scoped, for every tenant that
    already exists) so `AuthorizeAction` is not deny-by-default purely for
    lack of seed data against a real running Postgres -- the exact gap
    PR8's review found, previously masked by every use-case-level test's
    `_FakeAuthorizationPort`.

    Both seed functions remain explicitly PLACEHOLDER/dev-only (see their
    own module docstrings, design.md §16: "input de negocio pendiente") --
    calling them here does not make their CONTENT production-ready, it only
    ensures the MECHANISM actually runs.

    `tenant_id` values read back from `SELECT id FROM tenants` are
    server-generated UUIDs from an existing row, never external/request
    input -- safe to interpolate into `SET LOCAL` the same way
    `session_context.py`/`role_scope.py` document (bind parameters are not
    accepted by `SET`/`SET LOCAL` over the extended query protocol).
    `role_permissions` is tenant-scoped RLS but admits a write from ANY
    role once `app.tenant_id` is set (`role_permissions_tenant`,
    tests/rls/test_rbac_permissions_rls.py) -- `'admin'` is used here only
    because SOME valid role value must be set, not because it carries any
    special privilege for this write.

    Wired into `app/main.py`'s lifespan hook as of this session -- called
    once, against `open_runtime_connection()`, before the app starts
    serving traffic.
    """
    await seed_action_catalog(conn)
    tenant_rows = await conn.execute(text("SELECT id FROM tenants"))
    tenant_ids = [str(row[0]) for row in tenant_rows]
    for tenant_id in tenant_ids:
        await conn.execute(text(f"SET LOCAL app.tenant_id = '{tenant_id}'"))
        await conn.execute(text("SET LOCAL app.role = 'admin'"))
        await seed_default_role_permissions(conn, tenant_id)


def build_authorize_action(conn: AsyncConnection) -> AuthorizeAction:
    """Every RBAC-gated use case's `authorize` dependency -- a thin wrapper
    over `build_permission_service`. Kept as its own factory (rather than
    inlined at each `build_*` use-case function below) so there is exactly
    ONE place that decides how `AuthorizeAction` gets its
    `AuthorizationPort`."""
    return AuthorizeAction(build_permission_service(conn))


def build_runtime_session() -> EngineRuntimeSession:
    """Wires `AccessControlMiddleware`'s `RuntimeSessionPort` dependency
    (middleware.py's own docstring: "Composition root (task 10.2, not yet
    built) is where these get wired to the real Postgres engines") to the
    real `EngineRuntimeSession`, bound to `runtime_engine` -- never
    `engine`, for the same reason every other request-scoped connection in
    this module uses `runtime_engine`."""
    return EngineRuntimeSession(runtime_engine)


def build_access_token_verifier() -> JwtAccessTokenVerifier:
    """Wires `AccessControlMiddleware`'s `AccessTokenVerifierPort`
    dependency to the real `JwtAccessTokenVerifier`, using the SAME secret
    `build_access_token_issuer` below signs with (ADR-15) -- verifying
    exactly the tokens this process's own `Login`/`RefreshToken` mint."""
    return JwtAccessTokenVerifier(secret=settings.identity_access_token_secret)


def build_access_token_issuer(clock: ClockPort | None = None) -> JwtAccessTokenIssuer:
    return JwtAccessTokenIssuer(secret=settings.identity_access_token_secret, clock=clock or SystemClock())


# Process-wide singleton, deliberately NOT constructed per-request --
# `RotationReplayCachePort`'s whole purpose (design.md §17.4's 30s rotation
# grace period) requires the SAME cache instance to see a rotation written
# by one request and a replay read by a later one on this same process. See
# `TTLRotationReplayCache`'s own docstring for the multi-instance limitation
# this deliberately accepts (no cross-instance replication in the MVP).
_rotation_replay_cache = TTLRotationReplayCache()


def build_login(conn: AsyncConnection, *, http_client: httpx.AsyncClient) -> Login:
    """`conn` MUST be an `open_elevated_connection()` connection -- `Login`
    runs before any `app.*` GUC exists (see `Login`'s own docstring: its
    `user_directory`/`session_store`/`audit_log` all need the elevated,
    pre-auth `app.db.engine` connection privilege)."""
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
    """`conn` MUST be an `open_elevated_connection()` connection -- same
    pre-auth constraint as `build_login` above (`RefreshToken`'s own
    docstring: "deliberately does NOT accept a `TenantContext`... a
    pre-session operation")."""
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


def build_logout(conn: AsyncConnection) -> Logout:
    """`conn` MUST be an `open_runtime_connection()` connection with the
    caller's `app.*` GUCs already set -- unlike `Login`/`RefreshToken`,
    `Logout` takes a `TenantContext` (it runs behind
    `AccessControlMiddleware`, self-service, not RBAC-gated -- see its own
    docstring)."""
    return Logout(PostgresSessionStore(conn), SystemClock())


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
    """`reminder_channel=ConsoleReminderChannel()` -- the MVP
    `ReminderChannelPort` (design.md §2.5, `platform/outbound/channel/`),
    closing the gap that port's own module docstring flagged: "no concrete
    adapter ships in this PR... whichever future task wires the composition
    root (task 10.2) MUST supply a concrete `ReminderChannelPort`
    implementation"."""
    return SendReminder(
        build_authorize_action(conn),
        PostgresSchedulingRepository(conn),
        ConsoleReminderChannel(),
        PostgresAuditLog(conn),
    )


def build_connect_patient_calendar(conn: AsyncConnection) -> ConnectPatientCalendar:
    """`conn` MUST already be scoped `app.role='patient'` +
    `app.patient_id` for the calling actor -- satisfied automatically by
    `AccessControlMiddleware`/`set_session_context` when the authenticated
    caller IS a patient (`calendar_credentials_self`'s policy, see
    `CalendarCredentialRepositoryPort`'s docstring). Unlike
    `build_sync_appointment_to_calendar`, this does NOT need
    `RoleScopedCalendarCredentialRepository`'s dual-role re-scoping --
    `ConnectPatientCalendar` only ever touches `calendar_credentials`
    (patient-only policy), never `calendar_sync` (staff-only), in one flow."""
    return ConnectPatientCalendar(
        build_authorize_action(conn),
        PostgresPatientEmailLookup(conn),
        AesGcmVault(),
        PostgresCalendarCredentialRepository(conn),
        PostgresAuditLog(conn),
    )


def build_google_calendar_adapter(http_client: httpx.AsyncClient) -> GoogleCalendarAdapter:
    """Also the adapter task 10.1's OAuth2 callback route uses for
    `exchange_authorization_code` (added this session, see that method's
    own docstring) -- one adapter instance serves both the `CalendarSyncPort`
    contract and the authorization-code-exchange addition."""
    return GoogleCalendarAdapter(
        client_id=settings.calendar_google_client_id,
        client_secret=settings.calendar_google_client_secret,
        http_client=http_client,
    )


def build_register_staff(conn: AsyncConnection) -> RegisterStaff:
    """`conn` MUST be an `open_runtime_connection()` connection with the
    caller's `app.*` GUCs already set (RLS-scoped, RBAC-gated). Added this
    session (tasks.md task 11.5's `persist_and_audit` dispatch table) --
    `RegisterStaff` had no composition-root wiring before this batch (task
    10.1's own text scoped that router session to web-forms/auth/calendar
    only, deliberately not inventing staff HTTP routes; `persist_and_audit`
    is the first real caller)."""
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


__all__ = [
    "AppointmentSnapshotPort",
    "PostgresAppointmentSnapshotAdapter",
    "PostgresStaffStatusAdapter",
    "RoleScopedCalendarCredentialRepository",
    "StaffStatusPort",
    "bootstrap_rbac_catalog_and_grants",
    "build_access_token_issuer",
    "build_access_token_verifier",
    "build_authorize_action",
    "build_cancel_appointment",
    "build_connect_patient_calendar",
    "build_create_shift",
    "build_deactivate_staff",
    "build_edit_shift",
    "build_google_calendar_adapter",
    "build_login",
    "build_register_staff",
    "build_logout",
    "build_permission_service",
    "build_refresh_token",
    "build_reschedule_appointment",
    "build_runtime_session",
    "build_schedule_appointment",
    "build_send_reminder",
    "build_sync_appointment_to_calendar",
    "open_checkpointer_connection",
    "open_elevated_connection",
    "open_runtime_connection",
]
