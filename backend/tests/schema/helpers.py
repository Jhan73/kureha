"""Row-builder helpers for schema tests (design.md §4.1/§4.3).

Kept intentionally thin: each helper inserts exactly the columns a table
requires and returns the generated id, so tests can build only the fixture
graph they need (e.g. a scheduling test does not need a `consents` row).
"""

import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection


@asynccontextmanager
async def expect_violation(
    conn: AsyncConnection,
    exc_type: type[Exception] = IntegrityError,
    match: str | None = None,
) -> AsyncIterator[None]:
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
