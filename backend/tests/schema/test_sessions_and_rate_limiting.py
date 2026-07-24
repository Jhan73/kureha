"""Task 2.8: user_sessions, rate_counters, tenants.llm_daily_budget_tokens
(design.md §4.4, §17.4, §19).

`user_sessions` holds hashed refresh tokens with a rotation chain
(`rotated_from`) used to detect reuse of a revoked/rotated refresh (stolen
token signal, §17.4). `rate_counters` is infra for the auth/token and LLM
budget rate-limit dimensions (§19) -- `tenant_id` is nullable because the
pre-login IP-based auth limit has no tenant yet.
"""

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from tests.schema.helpers import expect_violation, make_site, make_tenant, make_user


async def make_user_session(
    conn, tenant_id, user_id, *, refresh_token_hash="hash-1", rotated_from=None
) -> str:
    result = await conn.execute(
        sa.text(
            "INSERT INTO user_sessions (tenant_id, user_id, refresh_token_hash, expires_at, rotated_from) "
            "VALUES (:tenant_id, :user_id, :hash, now() + interval '30 days', :rotated_from) "
            "RETURNING id"
        ),
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "hash": refresh_token_hash,
            "rotated_from": rotated_from,
        },
    )
    return str(result.scalar_one())


async def test_tenants_llm_daily_budget_tokens_defaults_to_100000(db_conn, tenant_id) -> None:
    row = (
        await db_conn.execute(
            sa.text("SELECT llm_daily_budget_tokens FROM tenants WHERE id = :id"), {"id": tenant_id}
        )
    ).one()
    assert row.llm_daily_budget_tokens == 100_000


async def test_user_session_refresh_token_hash_unique_within_tenant(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    user_id = await make_user(db_conn, tenant_id, site_id, role="reception")
    await make_user_session(db_conn, tenant_id, user_id, refresh_token_hash="dup-hash")

    async with expect_violation(db_conn, IntegrityError):
        await make_user_session(db_conn, tenant_id, user_id, refresh_token_hash="dup-hash")


async def test_user_session_refresh_token_hash_may_repeat_across_tenants(db_conn) -> None:
    tenant_a = await make_tenant(db_conn)
    tenant_b = await make_tenant(db_conn)
    site_a = await make_site(db_conn, tenant_a)
    site_b = await make_site(db_conn, tenant_b)
    user_a = await make_user(db_conn, tenant_a, site_a, role="reception")
    user_b = await make_user(db_conn, tenant_b, site_b, role="reception")

    await make_user_session(db_conn, tenant_a, user_a, refresh_token_hash="shared-hash")
    session_b = await make_user_session(db_conn, tenant_b, user_b, refresh_token_hash="shared-hash")
    assert session_b is not None


async def test_user_session_rotation_chain_links_rotated_from(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    user_id = await make_user(db_conn, tenant_id, site_id, role="reception")
    old_session = await make_user_session(db_conn, tenant_id, user_id, refresh_token_hash="old")

    new_session = await make_user_session(
        db_conn, tenant_id, user_id, refresh_token_hash="new", rotated_from=old_session
    )
    row = (
        await db_conn.execute(
            sa.text("SELECT rotated_from FROM user_sessions WHERE id = :id"), {"id": new_session}
        )
    ).one()
    assert str(row.rotated_from) == old_session


async def test_user_session_user_id_must_belong_to_same_tenant(db_conn) -> None:
    tenant_a = await make_tenant(db_conn)
    tenant_b = await make_tenant(db_conn)
    site_b = await make_site(db_conn, tenant_b)
    user_of_b = await make_user(db_conn, tenant_b, site_b, role="reception")

    async with expect_violation(db_conn):
        await make_user_session(db_conn, tenant_a, user_of_b)


async def test_rate_counter_upsert_is_atomic_on_dimension_subject_window(db_conn) -> None:
    await db_conn.execute(
        sa.text(
            "INSERT INTO rate_counters (dimension, subject, window_start, count) "
            "VALUES ('auth_ip', '203.0.113.1', date_trunc('hour', now()), 1)"
        )
    )
    await db_conn.execute(
        sa.text(
            "INSERT INTO rate_counters (dimension, subject, window_start, count) "
            "VALUES ('auth_ip', '203.0.113.1', date_trunc('hour', now()), 1) "
            "ON CONFLICT (dimension, subject, window_start) "
            "DO UPDATE SET count = rate_counters.count + 1"
        )
    )
    row = (
        await db_conn.execute(
            sa.text(
                "SELECT count FROM rate_counters WHERE dimension = 'auth_ip' AND subject = '203.0.113.1'"
            )
        )
    ).one()
    assert row.count == 2


async def test_rate_counter_tenant_id_is_nullable_for_pre_login_ip_limit(db_conn) -> None:
    result = await db_conn.execute(
        sa.text(
            "INSERT INTO rate_counters (tenant_id, dimension, subject, window_start, count) "
            "VALUES (NULL, 'auth_ip', '198.51.100.7', now(), 1) RETURNING tenant_id"
        )
    )
    assert result.scalar_one() is None


async def test_rate_counter_cleanup_deletes_only_rows_older_than_24h(db_conn) -> None:
    """Exercises the exact DELETE the cleanup job (task 2.11) runs, decoupled
    from the scheduling mechanism (pg_cron/Lambda) -- proves the query logic
    itself only removes rows past the 24h TTL."""
    await db_conn.execute(
        sa.text(
            "INSERT INTO rate_counters (dimension, subject, window_start, count) "
            "VALUES ('auth_ip', 'stale', now() - interval '25 hours', 1)"
        )
    )
    await db_conn.execute(
        sa.text(
            "INSERT INTO rate_counters (dimension, subject, window_start, count) "
            "VALUES ('auth_ip', 'fresh', now() - interval '1 hour', 1)"
        )
    )

    await db_conn.execute(
        sa.text("DELETE FROM rate_counters WHERE window_start < now() - interval '24 hours'")
    )

    # Scoped to the two subjects this test itself inserted -- an unscoped
    # `SELECT * FROM rate_counters` would also see any OTHER committed row
    # (e.g. `tests/platform/inbound/api/routers`'s router tests commit a real
    # 'testclient' row via the app's own rate-limit middleware) and make this
    # assertion depend on that other package's cleanup having already run,
    # which currently only holds due to pytest's alphabetical file-discovery
    # order -- not guaranteed under `pytest-randomly`/`pytest-xdist`/a partial
    # test-path run.
    remaining = (
        await db_conn.execute(
            sa.text("SELECT subject FROM rate_counters WHERE subject IN ('stale', 'fresh') ORDER BY subject")
        )
    ).all()
    assert [row.subject for row in remaining] == ["fresh"]
