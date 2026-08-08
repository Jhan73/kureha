import asyncio
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import timedelta

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.pool import NullPool

from app.config import settings
from app.db import create_engine, engine as _shared_engine, runtime_engine as _shared_runtime_engine
from app.main import app
from app.modules.governance.rbac.adapters.outbound.rbac.default_role_permissions import seed_default_role_permissions
from app.modules.identity.adapters.outbound.tokens.jwt_access_token_issuer import JwtAccessTokenIssuer
from app.shared_kernel.clock import SystemClock
from app.shared_kernel.tenant_context import TenantContext
from tests.rls.helpers import seed_appointment as _seed_appointment_row
from tests.rls.helpers import seed_consent as _seed_consent_row
from tests.rls.helpers import seed_consent_policy as _seed_consent_policy_row
from tests.schema.helpers import make_patient, make_professional, make_site, make_tenant, make_user, make_user_credentials


def _run(coro):
    # psycopg async needs SelectorEventLoop on Windows (Proactor raises InterfaceError).
    if sys.platform == "win32":
        return asyncio.run(coro, loop_factory=asyncio.SelectorEventLoop)
    return asyncio.run(coro)


async def _cleanup_committed_test_data() -> None:
    engine = create_engine(poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            async with conn.begin():
                await conn.execute(sa.text("DELETE FROM rate_counters WHERE subject = 'testclient'"))
    finally:
        await engine.dispose()
    await _shared_engine.dispose()
    await _shared_runtime_engine.dispose()


@pytest.fixture(scope="package")
def client() -> TestClient:
    # HTTPS base URL so Secure cookies from OAuth authorize are stored by the jar.
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as c:
        yield c
    _run(_cleanup_committed_test_data())


@asynccontextmanager
async def _committing_conn() -> AsyncGenerator[AsyncConnection]:
    engine = create_engine(poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            async with conn.begin():
                yield conn
    finally:
        await engine.dispose()


async def _make_tenant_with_rbac(conn: AsyncConnection) -> str:
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
        # `ScheduleAppointment`/`RescheduleAppointment` check
        # `StaffStatusPort.is_assignable` via `composition_root`'s
        # `PostgresStaffStatusAdapter`, which denies by default when no
        # `staff_members` row maps to `professional_id` -- a bare
        # `professionals` row is not enough for a schedulable professional.
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


async def _seed_current_consent(tenant_id: str, site_id: str, patient_id: str, *, version: str) -> None:
    async with _committing_conn() as conn:
        await _seed_consent_policy_row(conn, tenant_id, version=version, is_current=True)
        await _seed_consent_row(conn, tenant_id, site_id, patient_id, policy_version=version)


def seed_current_consent(tenant_id: str, site_id: str, patient_id: str, *, version: str = "2026.1") -> None:
    _run(_seed_current_consent(tenant_id, site_id, patient_id, version=version))


async def _seed_scheduled_appointment(
    tenant_id: str, site_id: str, patient_id: str, professional_id: str, availability_id: str, *, starts_at, ends_at
) -> str:
    async with _committing_conn() as conn:
        return await _seed_appointment_row(
            conn, tenant_id, site_id, patient_id, professional_id, availability_id, starts_at=starts_at, ends_at=ends_at
        )


def seed_scheduled_appointment(
    tenant_id: str, site_id: str, patient_id: str, professional_id: str, availability_id: str, *, starts_at, ends_at
) -> str:
    return _run(
        _seed_scheduled_appointment(
            tenant_id, site_id, patient_id, professional_id, availability_id, starts_at=starts_at, ends_at=ends_at
        )
    )


async def _mint_access_token(*, tenant_id: str, site_id: str, role: str, user_id: str) -> str:
    issuer = JwtAccessTokenIssuer(secret=settings.identity_access_token_secret, clock=SystemClock())
    ctx = TenantContext(tenant_id=tenant_id, role=role, site_id=site_id, actor_id=user_id)
    return await issuer.issue(ctx, ttl=timedelta(minutes=10))


def mint_access_token(*, tenant_id: str, site_id: str, role: str, user_id: str) -> str:
    return _run(_mint_access_token(tenant_id=tenant_id, site_id=site_id, role=role, user_id=user_id))


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def reset_auth_ip_rate_limit_budget() -> None:
    async def _reset() -> None:
        async with _committing_conn() as conn:
            await conn.execute(
                sa.text("DELETE FROM rate_counters WHERE dimension = 'auth_ip' AND subject = 'testclient'")
            )

    _run(_reset())


def reset_ops_bootstrap_rate_limit_budget(operator_key_id: str) -> None:
    async def _reset() -> None:
        async with _committing_conn() as conn:
            await conn.execute(
                sa.text("DELETE FROM rate_counters WHERE dimension = 'ops_bootstrap' AND subject = :subject"),
                {"subject": operator_key_id},
            )

    _run(_reset())


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
