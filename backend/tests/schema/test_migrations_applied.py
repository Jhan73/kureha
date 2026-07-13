"""Smoke test for tasks 2.1-2.4: confirms every table this batch introduces
exists after the session-scoped `_migrated_schema` fixture (conftest.py) ran
Alembic upgrade -> downgrade -> upgrade to head.
"""

import sqlalchemy as sa

EXPECTED_TABLES = {
    "tenants",
    "sites",
    "professionals",
    "patients",
    "users",
    "availability",
    "appointments",
    "consent_policies",
    "consents",
    "audit_logs",
}


async def test_all_phase_2_1_to_2_4_tables_exist(db_conn) -> None:
    result = await db_conn.execute(
        sa.text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = ANY(:names)"
        ),
        {"names": list(EXPECTED_TABLES)},
    )
    found = {row.table_name for row in result}
    assert found == EXPECTED_TABLES


async def test_alembic_is_at_head_after_upgrade_downgrade_upgrade_cycle(db_conn) -> None:
    result = await db_conn.execute(sa.text("SELECT version_num FROM alembic_version"))
    versions = {row.version_num for row in result}
    assert len(versions) == 1
