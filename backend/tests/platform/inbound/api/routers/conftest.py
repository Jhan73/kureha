"""Shared fixtures/helpers for task 10.1's router tests.

**Why plain `def test_...` (sync), never `async def`, in this package --
deliberately, unlike almost every other test file in this codebase:**
`app/main.py`'s `app` uses the process-wide `app.db.engine`/
`app.db.runtime_engine` singletons (`app/db.py`'s own docstring). Starlette's
`TestClient` dispatches every request through ONE dedicated background
thread + event loop for the lifetime of a single `with TestClient(app) as
client:` block (this module's `client` fixture, `scope="module"` --
one portal for the whole file). Confirmed empirically THIS session: writing
these tests as `async def` (pytest-asyncio's default, function-scoped event
loop per test) caused `client.get()/post()` calls from inside each test's OWN
loop to route the app's `engine`/`runtime_engine` connections through
DIFFERENT loops across tests, and a pooled connection created under one
test's loop being handed back out under a later test's DIFFERENT loop broke
with an opaque `AttributeError`/`ConnectionDoesNotExistError` from asyncpg's
Proactor transport -- the exact hazard `tests/conftest.py`'s `db_conn`
docstring warns about, but for the app's OWN shared singleton engines rather
than a test-owned one (which is why `db_conn`/`rls_conn`'s existing
`NullPool`-per-test pattern does not, by itself, protect this case). Plain
`def` test functions have NO event loop of their own at all -- `client.get()`
always dispatches into the SAME portal thread/loop for the whole module,
and any async SEEDING helper below runs via a throwaway, isolated
`asyncio.run(...)` call using its OWN fresh `NullPool` engine (never the
app's shared singletons), so it never competes with the portal's loop
either."""

import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.pool import NullPool

# PR 12 batch 2, discovered while writing `test_chat.py`'s first test to
# genuinely complete a successful `graph.ainvoke()` end to end (every prior
# test in this package either failed pre-graph, at 401, or asserted a
# generic 500 for a DIFFERENT reason before this point was ever reached):
# `POST /chat` (`chat.py`) constructs a real `AsyncPostgresSaver` via
# `composition_root.open_checkpointer_connection()`, which requires a raw
# `psycopg.AsyncConnection` -- `psycopg`'s async mode raises `InterfaceError`
# under `asyncio`'s DEFAULT event loop on Windows (`ProactorEventLoop`; it
# only supports a selector-based loop). Confirmed empirically THIS session:
# `WindowsSelectorEventLoopPolicy` fixes it, with no effect on non-Windows
# CI. This is a genuine, PRE-EXISTING local-Windows-dev-only gap (production
# targets AWS ECS/Linux per design.md §20, never affected) -- NOT something
# any batch-1/2 adapter caused; it was simply never exercised before because
# every earlier test in this package stopped short of a real, successful
# checkpointer connection. Test-only fix, matching this module's own
# existing precedent of documented, empirically-found Windows event-loop
# workarounds for `TestClient`'s portal thread (see this module's own
# docstring above).
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.config import settings
from app.db import create_engine, engine as _shared_engine, runtime_engine as _shared_runtime_engine
from app.main import app
from app.modules.governance.rbac.adapters.outbound.rbac.default_role_permissions import seed_default_role_permissions
from app.modules.identity.adapters.outbound.tokens.jwt_access_token_issuer import JwtAccessTokenIssuer
from app.shared_kernel.clock import SystemClock
from app.shared_kernel.tenant_context import TenantContext
from tests.schema.helpers import make_patient, make_professional, make_site, make_tenant, make_user, make_user_credentials

async def _cleanup_committed_test_data() -> None:
    """Undoes the ONE GLOBAL, non-tenant-scoped, cleanly-removable REAL,
    COMMITTED side effect this test package's `client` fixture causes:
    `AuthRateLimitMiddleware`'s `rate_counters` row for the `testclient` IP
    (`/auth/login`/`/auth/refresh` are both rate-limit-protected paths, see
    `app/main.py`'s `_AUTH_RATE_LIMIT_PROTECTED_PREFIXES`).

    **Deliberately does NOT delete `action_permissions` (the RBAC catalog)
    or this package's own tenant-scoped rows** (tenants/sites/users/
    patients/appointments/etc.) -- confirmed empirically THIS session, in
    order, both are structurally impossible once this package's tests have
    run:
    1. `audit_logs` is genuinely append-only (a DB trigger raises
       `"audit_logs is append-only (DELETE not allowed)"` -- design.md
       §4.3's hash-chain integrity guarantee), so a `tenants` row that ever
       received an audit entry can never be deleted (`audit_logs.tenant_id
       REFERENCES tenants(id)`).
    2. Because those tenants are therefore permanent, their
       `role_permissions` rows are too -- and `action_permissions` cannot
       be deleted while ANY `role_permissions` row still references it
       (`role_permissions_action_fkey`). `app/main.py`'s lifespan calling
       `bootstrap_rbac_catalog_and_grants` for real (tasks.md task 10.2's
       own forward pointer, closed this session) against the shared,
       session-persisting dev database is therefore a ONE-WAY change to
       this test suite's assumptions -- any schema test that assumed
       `action_permissions` starts empty needed updating to use a
       never-seeded key instead (see `tests/schema/test_rbac_tables.py`'s
       `test_action_permissions_requires_hitl_defaults_false`). This mirrors
       real production behavior (tenants/audit trails/the RBAC catalog are
       not deleted in this MVP) rather than working around it."""
    engine = create_engine(poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            async with conn.begin():
                await conn.execute(sa.text("DELETE FROM rate_counters WHERE subject = 'testclient'"))
    finally:
        await engine.dispose()
    # Empties the pool of connections opened under this package's own
    # portal-thread event loop -- otherwise a LATER test using
    # `app.db.engine`/`app.db.runtime_engine` DIRECTLY (not through a
    # request) could be handed one back under a DIFFERENT loop and crash
    # the same way this module's own docstring describes.
    await _shared_engine.dispose()
    await _shared_runtime_engine.dispose()


@pytest.fixture(scope="package")
def client() -> TestClient:
    """`scope="package"`, deliberately, not `"module"` or `"session"` --
    confirmed empirically THIS session: `app.db.engine`/`app.db.runtime_engine`
    are PROCESS-WIDE singletons, and each `with TestClient(app) as c:` block
    spins its OWN dedicated portal thread/event loop for its lifetime. A
    module-scoped fixture gives EACH test FILE its own portal/loop -- fine
    within one file, but the pool's idle connections (created under file
    A's portal loop) get handed back out once file B's DIFFERENT portal
    starts, which breaks with the exact opaque `AttributeError`/
    `RuntimeError: Event loop is closed` this module's own docstring
    describes, just one level up (across files instead of across tests). ONE
    portal for the whole `tests/platform/inbound/api/routers/` package
    avoids that. NOT `scope="session"` either -- confirmed empirically:
    session scope defers `_cleanup_committed_test_data()` (this fixture's
    teardown, below) to the very END of the ENTIRE test session, by which
    point unrelated test files elsewhere in the suite have ALREADY run
    against this package's polluted, committed data and failed. `"package"`
    tears down (and cleans up) as soon as the LAST test in this specific
    package finishes, before any later, unrelated test file runs.

    `raise_server_exceptions=False` -- Starlette's `TestClient` defaults to
    RE-RAISING any exception that reaches `ServerErrorMiddleware` (Python-
    level, in the test process) instead of returning the actual
    JSONResponse `register_exception_handlers`' catch-all `Exception`
    handler produced. Since every domain error in this codebase (a
    `NotFoundError`/`ActionNotPermittedError`/etc, none of which are
    `HTTPException`) is handled at EXACTLY that layer (see `errors.py`'s
    own module docstring on the MRO-walk resolution), the default would
    make every "(c) assert the error envelope" test below fail with a
    raised Python exception instead of an inspectable `response`."""
    # `base_url="https://testserver"` -- `/calendar/oauth/authorize` sets its
    # nonce cookie with `secure=True` (a real deployment is HTTPS-only); a
    # `Secure` cookie is never stored/resent over a plain `http://` base URL
    # by any spec-compliant cookie jar (confirmed empirically THIS session --
    # the default `http://testserver` silently dropped the cookie, breaking
    # the `/authorize` -> `/callback` round trip).
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as c:
        yield c
    asyncio.run(_cleanup_committed_test_data())


@asynccontextmanager
async def _committing_conn() -> AsyncIterator[AsyncConnection]:
    """A throwaway, `NullPool`-backed, elevated (`app_user`) connection that
    COMMITS on a clean exit -- unlike `tests/conftest.py`'s `db_conn`/
    `rls_conn` (which roll back for per-test isolation), router tests need
    seeded data to actually be VISIBLE to the app's own, separate
    connections once `client.post(...)` runs. Always constructed fresh
    (never `app.composition_root.open_elevated_connection()`, which is
    bound to the shared `engine` singleton the app's own portal thread
    uses) -- see this module's docstring."""
    engine = create_engine(poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            async with conn.begin():
                yield conn
    finally:
        await engine.dispose()


def _run(coro):
    """Runs one async helper to completion in its OWN, brand-new, isolated
    event loop -- see this module's docstring for why this (not `async def`
    test functions) is the safe way to do async setup here."""
    return asyncio.run(coro)


async def _make_tenant_with_rbac(conn: AsyncConnection) -> str:
    """`bootstrap_rbac_catalog_and_grants` (`composition_root.py`) only
    seeds `role_permissions` for tenants that already existed at APP
    STARTUP (`app/main.py`'s lifespan, which runs ONCE before this module's
    `client` fixture's first test) -- a tenant created by a LATER test has
    no `role_permissions` rows at all, and `PermissionService` denies
    everything by construction (deny-by-default). Every seed helper in this
    module MUST seed the SAME tenant-scoped grants here (the global
    `action_permissions` catalog is already seeded once at startup, no need
    to repeat that part)."""
    tenant_id = await make_tenant(conn)
    await seed_default_role_permissions(conn, tenant_id)
    return tenant_id


async def _seed_reception_actor(email: str) -> dict:
    async with _committing_conn() as conn:
        tenant_id = await _make_tenant_with_rbac(conn)
        site_id = await make_site(conn, tenant_id)
        user_id = await make_user(conn, tenant_id, site_id, role="reception")
        await make_user_credentials(conn, tenant_id, user_id, email=email)
    return {"tenant_id": tenant_id, "site_id": site_id, "user_id": user_id, "email": email}


def seed_reception_actor(*, email: str = "reception@example.com") -> dict:
    """Seeds tenant/site/user(+credentials) for a `reception` actor with no
    `staff_members` row (`LiveActor.is_active`'s "`staff_status is None`"
    branch applies)."""
    return _run(_seed_reception_actor(email))


async def _seed_patient_actor(patient_document_number: str | None) -> dict:
    async with _committing_conn() as conn:
        tenant_id = await _make_tenant_with_rbac(conn)
        site_id = await make_site(conn, tenant_id)
        patient_id = await make_patient(conn, tenant_id, site_id=site_id, document_number=patient_document_number)
        user_id = await make_user(conn, tenant_id, site_id, role="patient", patient_id=patient_id)
    return {"tenant_id": tenant_id, "site_id": site_id, "user_id": user_id, "patient_id": patient_id}


def seed_patient_actor(*, patient_document_number: str | None = None) -> dict:
    return _run(_seed_patient_actor(patient_document_number))


async def _seed_available_slot(tenant_id: str, site_id: str, *, starts_at, ends_at) -> dict:
    async with _committing_conn() as conn:
        professional_id = await make_professional(conn, tenant_id, site_id)
        # `ScheduleAppointment`/`RescheduleAppointment` check `StaffStatusPort
        # .is_assignable` (tasks.md task 8.4) via `composition_root`'s
        # `PostgresStaffStatusAdapter`, which denies by default when NO
        # `staff_members` row maps to `professional_id` at all (see that
        # adapter's own docstring) -- a bare `professionals` row is not
        # enough on its own for a schedulable professional.
        await conn.execute(
            sa.text(
                "INSERT INTO staff_members (tenant_id, site_id, professional_id, name, operational_role) "
                "VALUES (:t, :s, :p, 'Test Professional', 'professional')"
            ),
            {"t": tenant_id, "s": site_id, "p": professional_id},
        )
        result = await conn.execute(
            sa.text(
                "INSERT INTO availability (tenant_id, site_id, professional_id, starts_at, ends_at) "
                "VALUES (:t, :s, :p, :starts_at, :ends_at) RETURNING id"
            ),
            {"t": tenant_id, "s": site_id, "p": professional_id, "starts_at": starts_at, "ends_at": ends_at},
        )
        availability_id = str(result.scalar_one())
    return {"professional_id": professional_id, "availability_id": availability_id}


def seed_available_slot(tenant_id: str, site_id: str, *, starts_at, ends_at) -> dict:
    return _run(_seed_available_slot(tenant_id, site_id, starts_at=starts_at, ends_at=ends_at))


async def _mint_access_token(*, tenant_id: str, site_id: str, role: str, user_id: str) -> str:
    issuer = JwtAccessTokenIssuer(secret=settings.identity_access_token_secret, clock=SystemClock())
    ctx = TenantContext(tenant_id=tenant_id, role=role, site_id=site_id, actor_id=user_id)
    return await issuer.issue(ctx, ttl=timedelta(minutes=10))


def mint_access_token(*, tenant_id: str, site_id: str, role: str, user_id: str) -> str:
    return _run(_mint_access_token(tenant_id=tenant_id, site_id=site_id, role=role, user_id=user_id))


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def count_audit_rows(tenant_id: str, action: str) -> int:
    async def _count() -> int:
        async with _committing_conn() as conn:
            return (
                await conn.execute(
                    sa.text("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND action = :a"),
                    {"t": tenant_id, "a": action},
                )
            ).scalar_one()

    return _run(_count())
