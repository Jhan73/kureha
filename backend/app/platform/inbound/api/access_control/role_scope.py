from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_NIL_UUID = "00000000-0000-0000-0000-000000000000"


async def set_role_scope(
    conn: AsyncConnection,
    *,
    role: str,
    patient_id: str | None = None,
    professional_id: str | None = None,
) -> None:
    await conn.execute(text(f"SET LOCAL app.role = '{role}'"))
    await conn.execute(text(f"SET LOCAL app.patient_id = '{patient_id or _NIL_UUID}'"))
    await conn.execute(text(f"SET LOCAL app.professional_id = '{professional_id or _NIL_UUID}'"))


@asynccontextmanager
async def scoped_as_patient(conn: AsyncConnection, *, patient_id: str, restore_role: str) -> AsyncIterator[None]:
    await set_role_scope(conn, role="patient", patient_id=patient_id)
    try:
        yield
    finally:
        await set_role_scope(conn, role=restore_role)


@asynccontextmanager
async def scoped_as_admin(conn: AsyncConnection, *, restore_role: str) -> AsyncIterator[None]:
    await set_role_scope(conn, role="admin")
    try:
        yield
    finally:
        await set_role_scope(conn, role=restore_role)
