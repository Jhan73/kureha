"""Task 11.4: `ActionRiskReader` -- integration test hitting the real,
global `action_permissions` catalog (no RLS, design.md §4.4) through
`db_conn` (rolled back per test, same convention as `test_rbac_tables.py`,
not `rls_conn`, since this table has no tenant-scoped policy to exercise)."""

import sqlalchemy as sa

from app.modules.governance.rbac.adapters.outbound.rbac.action_risk_reader import ActionRiskReader


async def test_get_reads_the_configured_requires_hitl_and_threshold(db_conn) -> None:
    await db_conn.execute(
        sa.text(
            "INSERT INTO action_permissions (key, description, requires_hitl, bulk_cancel_threshold) "
            "VALUES ('appointment:cancel', 'Cancel an appointment', true, 5)"
        )
    )
    reader = ActionRiskReader(db_conn)

    config = await reader.get("appointment:cancel")

    assert config.requires_hitl is True
    assert config.bulk_cancel_threshold == 5


async def test_get_reflects_ddl_defaults_when_row_omits_them(db_conn) -> None:
    await db_conn.execute(
        sa.text("INSERT INTO action_permissions (key, description) VALUES ('appointment:reschedule', 'Reschedule')")
    )
    reader = ActionRiskReader(db_conn)

    config = await reader.get("appointment:reschedule")

    assert config.requires_hitl is False
    assert config.bulk_cancel_threshold == 3


async def test_get_denies_by_default_for_an_action_not_in_the_catalog(db_conn) -> None:
    reader = ActionRiskReader(db_conn)

    config = await reader.get("test_probe:never_registered")

    assert config.requires_hitl is True
    assert config.bulk_cancel_threshold == 0


async def test_a_fresh_reader_instance_never_sees_a_stale_value(db_conn) -> None:
    """Mirrors `PermissionService`'s own
    `test_a_fresh_service_instance_never_sees_a_stale_memo` -- no
    cross-request cache means a config change is visible immediately to a
    newly constructed reader, without any invalidation mechanism to get
    wrong."""
    await db_conn.execute(
        sa.text(
            "INSERT INTO action_permissions (key, description, bulk_cancel_threshold) "
            "VALUES ('appointment:cancel', 'Cancel', 3)"
        )
    )
    first_reader = ActionRiskReader(db_conn)
    assert (await first_reader.get("appointment:cancel")).bulk_cancel_threshold == 3

    await db_conn.execute(
        sa.text("UPDATE action_permissions SET bulk_cancel_threshold = 10 WHERE key = 'appointment:cancel'")
    )

    second_reader = ActionRiskReader(db_conn)
    assert (await second_reader.get("appointment:cancel")).bulk_cancel_threshold == 10
