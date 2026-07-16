"""Task 5.3: `PostgresRateCounterStore` -- `RateCounterStorePort` adapter
over `rate_counters` (design.md §19), the atomic UPSERT-by-window pattern
already proven in `tests/schema/test_sessions_and_rate_limiting.py`
(`test_rate_counter_upsert_is_atomic_on_dimension_subject_window`).

`rate_counters` has NO RLS (design.md §4.4: "vive fuera de las policies de
dato de paciente... no la lee el dominio de negocio") -- uses `db_conn`
(elevated), matching every other adapter that documents an elevated-
connection exception, not `rls_conn`."""

from datetime import datetime, timezone

import sqlalchemy as sa

from app.platform.inbound.api.rate_limit.adapters.postgres_rate_counter_store import PostgresRateCounterStore

_WINDOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


async def test_first_increment_creates_a_row_with_count_1(db_conn) -> None:
    store = PostgresRateCounterStore(db_conn)
    new_count = await store.increment(dimension="auth_ip", subject="203.0.113.5", window_start=_WINDOW)
    assert new_count == 1


async def test_repeated_increments_in_the_same_window_accumulate(db_conn) -> None:
    store = PostgresRateCounterStore(db_conn)
    await store.increment(dimension="auth_ip", subject="203.0.113.6", window_start=_WINDOW)
    await store.increment(dimension="auth_ip", subject="203.0.113.6", window_start=_WINDOW)
    new_count = await store.increment(dimension="auth_ip", subject="203.0.113.6", window_start=_WINDOW)
    assert new_count == 3


async def test_increment_by_an_arbitrary_amount_for_the_llm_tokens_dimension(db_conn, tenant_id) -> None:
    """design.md §19: LLM budget usage is UPSERTed by `tokens_used`, not by
    1 per call."""
    store = PostgresRateCounterStore(db_conn)
    await store.increment(
        dimension="llm_tokens", subject=tenant_id, window_start=_WINDOW, by=450, tenant_id=tenant_id
    )
    new_count = await store.increment(
        dimension="llm_tokens", subject=tenant_id, window_start=_WINDOW, by=150, tenant_id=tenant_id
    )
    assert new_count == 600


async def test_different_windows_do_not_share_a_counter(db_conn) -> None:
    store = PostgresRateCounterStore(db_conn)
    window_a = _WINDOW
    window_b = datetime(2026, 1, 1, 13, 0, 0, tzinfo=timezone.utc)

    await store.increment(dimension="auth_ip", subject="203.0.113.7", window_start=window_a)
    new_count = await store.increment(dimension="auth_ip", subject="203.0.113.7", window_start=window_b)

    assert new_count == 1


async def test_tenant_id_is_persisted_when_given(db_conn, tenant_id) -> None:
    store = PostgresRateCounterStore(db_conn)
    await store.increment(
        dimension="llm_tokens", subject=tenant_id, window_start=_WINDOW, tenant_id=tenant_id
    )

    row = (
        await db_conn.execute(
            sa.text(
                "SELECT tenant_id FROM rate_counters "
                "WHERE dimension = 'llm_tokens' AND subject = :subject AND window_start = :window"
            ),
            {"subject": tenant_id, "window": _WINDOW},
        )
    ).one()
    assert str(row.tenant_id) == tenant_id


async def test_tenant_id_is_null_for_pre_login_ip_dimension(db_conn) -> None:
    store = PostgresRateCounterStore(db_conn)
    await store.increment(dimension="auth_ip", subject="203.0.113.8", window_start=_WINDOW)

    row = (
        await db_conn.execute(
            sa.text(
                "SELECT tenant_id FROM rate_counters "
                "WHERE dimension = 'auth_ip' AND subject = '203.0.113.8' AND window_start = :window"
            ),
            {"window": _WINDOW},
        )
    ).one()
    assert row.tenant_id is None


async def test_peek_returns_zero_for_a_never_seen_key_without_creating_a_row(db_conn) -> None:
    store = PostgresRateCounterStore(db_conn)

    count = await store.peek(dimension="auth_ip", subject="203.0.113.99", window_start=_WINDOW)

    assert count == 0
    row = (
        await db_conn.execute(
            sa.text(
                "SELECT 1 FROM rate_counters "
                "WHERE dimension = 'auth_ip' AND subject = '203.0.113.99' AND window_start = :window"
            ),
            {"window": _WINDOW},
        )
    ).one_or_none()
    assert row is None


async def test_peek_returns_the_current_count_without_mutating_it(db_conn) -> None:
    store = PostgresRateCounterStore(db_conn)
    await store.increment(dimension="auth_ip", subject="203.0.113.100", window_start=_WINDOW, by=3)

    first_peek = await store.peek(dimension="auth_ip", subject="203.0.113.100", window_start=_WINDOW)
    second_peek = await store.peek(dimension="auth_ip", subject="203.0.113.100", window_start=_WINDOW)

    assert first_peek == 3
    assert second_peek == 3
