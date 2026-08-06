import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection


@asynccontextmanager
async def expect_violation(
    conn: AsyncConnection,
    exc_type: type[Exception] = IntegrityError,
    match: str | None = None,
) -> AsyncGenerator[None]:
    """Wraps the `pytest.raises(...) + conn.begin_nested()` pair repeated
    across every constraint-violation test: the savepoint keeps the test's
    outer transaction (used for per-test isolation, see conftest.py's
    `db_conn`) alive after the expected error."""
    with pytest.raises(exc_type, match=match):
        async with conn.begin_nested():
            yield


async def make_tenant(conn: AsyncConnection, *, name: str = "Test Clinic") -> str:
    result = await conn.execute(
        sa.text("INSERT INTO tenants (name) VALUES (:name) RETURNING id"),
        {"name": name},
    )
    return str(result.scalar_one())


async def make_site(conn: AsyncConnection, tenant_id: str, *, name: str = "Main Site") -> str:
    result = await conn.execute(
        sa.text("INSERT INTO sites (tenant_id, name) VALUES (:tenant_id, :name) RETURNING id"),
        {"tenant_id": tenant_id, "name": name},
    )
    return str(result.scalar_one())


async def make_professional(
    conn: AsyncConnection, tenant_id: str, site_id: str, *, name: str = "Test Professional"
) -> str:
    result = await conn.execute(
        sa.text(
            "INSERT INTO professionals (tenant_id, site_id, name) "
            "VALUES (:tenant_id, :site_id, :name) RETURNING id"
        ),
        {"tenant_id": tenant_id, "site_id": site_id, "name": name},
    )
    return str(result.scalar_one())


async def make_patient(
    conn: AsyncConnection,
    tenant_id: str,
    *,
    site_id: str | None = None,
    document_number: str | None = None,
    name: str = "Test Patient",
) -> str:
    result = await conn.execute(
        sa.text(
            "INSERT INTO patients (tenant_id, site_id, name, document_number) "
            "VALUES (:tenant_id, :site_id, :name, :document_number) RETURNING id"
        ),
        {
            "tenant_id": tenant_id,
            "site_id": site_id,
            "name": name,
            "document_number": document_number or f"DNI-{uuid.uuid4().hex[:8]}",
        },
    )
    return str(result.scalar_one())


async def make_user(
    conn: AsyncConnection,
    tenant_id: str,
    site_id: str,
    *,
    role: str,
    patient_id: str | None = None,
    professional_id: str | None = None,
) -> str:
    result = await conn.execute(
        sa.text(
            "INSERT INTO users (tenant_id, site_id, role, patient_id, professional_id) "
            "VALUES (:tenant_id, :site_id, :role, :patient_id, :professional_id) "
            "RETURNING id"
        ),
        {
            "tenant_id": tenant_id,
            "site_id": site_id,
            "role": role,
            "patient_id": patient_id,
            "professional_id": professional_id,
        },
    )
    return str(result.scalar_one())


async def make_user_credentials(
    conn: AsyncConnection,
    tenant_id: str,
    user_id: str,
    *,
    email: str,
    auth_subject: str | None = None,
    email_verified_at: str | None = None,
) -> str:
    result = await conn.execute(
        sa.text(
            "INSERT INTO user_credentials (tenant_id, user_id, email, auth_subject, email_verified_at) "
            "VALUES (:tenant_id, :user_id, :email, :auth_subject, :email_verified_at) "
            "RETURNING id"
        ),
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "email": email,
            "auth_subject": auth_subject,
            "email_verified_at": email_verified_at,
        },
    )
    return str(result.scalar_one())
