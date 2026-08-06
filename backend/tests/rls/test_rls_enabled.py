import sqlalchemy as sa

RLS_TABLES = {
    "sites",
    "professionals",
    "users",
    "patients",
    "availability",
    "appointments",
    "consent_policies",
    "consents",
    "audit_logs",
    "role_permissions",
    "user_permissions",
    "staff_members",
    "shifts",
    "calendar_credentials",
    "calendar_sync",
    "user_sessions",
}

NO_RLS_TABLES = {"tenants", "action_permissions", "rate_counters"}


async def test_every_rls_table_has_enable_and_force(db_conn) -> None:
    result = await db_conn.execute(
        sa.text(
            "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relname = ANY(:names) AND relkind = 'r'"
        ),
        {"names": list(RLS_TABLES)},
    )
    rows = {row.relname: (row.relrowsecurity, row.relforcerowsecurity) for row in result}
    assert set(rows) == RLS_TABLES
    for table, (enabled, forced) in rows.items():
        assert enabled is True, f"{table} does not have RLS enabled"
        assert forced is True, f"{table} does not have RLS forced"


async def test_explicitly_excluded_tables_have_no_rls(db_conn) -> None:
    result = await db_conn.execute(
        sa.text(
            "SELECT relname, relrowsecurity FROM pg_class "
            "WHERE relname = ANY(:names) AND relkind = 'r'"
        ),
        {"names": list(NO_RLS_TABLES)},
    )
    rows = {row.relname: row.relrowsecurity for row in result}
    assert set(rows) == NO_RLS_TABLES
    for table, enabled in rows.items():
        assert enabled is False, f"{table} unexpectedly has RLS enabled"
