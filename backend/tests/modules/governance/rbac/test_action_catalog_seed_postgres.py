"""Task 3.6: `seed_action_catalog` -- the code-driven seed mechanism for the
global `action_permissions` catalog (design.md §4.4: "catalogo global...
sin RLS"). Before this task nothing populated this table outside of a
handful of test-only single-row inserts (PR8 review finding) --
`AuthorizeAction` denied every action by construction against a real
Postgres. Integration test against `rls_conn` (not a fake port) so the gap
this task closes is actually proven closed, not just scaffolded."""

import sqlalchemy as sa

from app.modules.governance.rbac.adapters.outbound.rbac.action_catalog import (
    ACTION_CATALOG,
    seed_action_catalog,
)

_EXPECTED_KEYS = {
    "appointment:create",
    "appointment:reschedule",
    "appointment:cancel",
    "appointment:view",
    "session:revoke_all",
    "staff:register",
    "staff:deactivate",
    "shift:create",
    "shift:edit",
    "calendar:connect",
}


async def test_seed_action_catalog_inserts_every_call_site_key(rls_conn) -> None:
    await seed_action_catalog(rls_conn)

    rows = (await rls_conn.execute(sa.text("SELECT key FROM action_permissions"))).all()
    seeded_keys = {row.key for row in rows}

    assert {entry.key for entry in ACTION_CATALOG} == _EXPECTED_KEYS
    assert _EXPECTED_KEYS <= seeded_keys


async def test_seed_action_catalog_is_idempotent(rls_conn) -> None:
    await seed_action_catalog(rls_conn)
    await seed_action_catalog(rls_conn)  # must not raise a PK violation or duplicate rows

    row = (
        await rls_conn.execute(
            sa.text("SELECT count(*) AS n FROM action_permissions WHERE key = 'appointment:create'")
        )
    ).one()
    assert row.n == 1
