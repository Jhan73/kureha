"""Task 4.3/4.4/4.5: `PostgresSessionStore` -- `SessionStorePort` adapter
over `user_sessions` (design.md §17.4). Uses `db_conn` (elevated/`app_user`)
-- the adapter's SQL is identical regardless of which role runs it (every
query is explicitly scoped by its own WHERE-clause parameters, not `app.*`
GUCs); RLS enforcement itself is covered separately by
tests/rls/test_sessions_rls.py against the underlying table."""

from datetime import datetime, timedelta, timezone

from tests.schema.helpers import make_site, make_tenant, make_user

from app.modules.identity.adapters.outbound.postgres.session_store import PostgresSessionStore

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def _make_user(db_conn, tenant_id) -> str:
    site_id = await make_site(db_conn, tenant_id)
    return await make_user(db_conn, tenant_id, site_id, role="reception")


async def test_create_then_find_by_hash_round_trips(db_conn, tenant_id) -> None:
    user_id = await _make_user(db_conn, tenant_id)
    store = PostgresSessionStore(db_conn)

    created = await store.create(
        tenant_id, user_id, refresh_token_hash="hash-1", expires_at=_NOW + timedelta(days=30)
    )

    found = await store.find_by_hash("hash-1")
    assert found is not None
    assert found.id == created.id
    assert found.tenant_id == tenant_id
    assert found.user_id == user_id
    assert found.revoked_at is None


async def test_find_by_hash_returns_none_for_unknown_hash(db_conn, tenant_id) -> None:
    store = PostgresSessionStore(db_conn)
    assert await store.find_by_hash("never-issued") is None


async def test_find_by_hash_is_global_not_tenant_scoped(db_conn) -> None:
    tenant_a = await make_tenant(db_conn)
    tenant_b = await make_tenant(db_conn)
    site_a = await make_site(db_conn, tenant_a)
    site_b = await make_site(db_conn, tenant_b)
    user_a = await make_user(db_conn, tenant_a, site_a, role="reception")
    user_b = await make_user(db_conn, tenant_b, site_b, role="reception")

    store = PostgresSessionStore(db_conn)
    await store.create(tenant_a, user_a, refresh_token_hash="hash-a", expires_at=_NOW + timedelta(days=30))
    await store.create(tenant_b, user_b, refresh_token_hash="hash-b", expires_at=_NOW + timedelta(days=30))

    found = await store.find_by_hash("hash-b")
    assert found is not None
    assert found.tenant_id == tenant_b


async def test_get_by_id_scoped_to_tenant(db_conn, tenant_id) -> None:
    user_id = await _make_user(db_conn, tenant_id)
    store = PostgresSessionStore(db_conn)
    created = await store.create(tenant_id, user_id, refresh_token_hash="h", expires_at=_NOW + timedelta(days=30))

    other_tenant = await make_tenant(db_conn)
    assert await store.get_by_id(other_tenant, created.id) is None
    assert (await store.get_by_id(tenant_id, created.id)).id == created.id


async def test_revoke_sets_revoked_at(db_conn, tenant_id) -> None:
    user_id = await _make_user(db_conn, tenant_id)
    store = PostgresSessionStore(db_conn)
    created = await store.create(tenant_id, user_id, refresh_token_hash="h", expires_at=_NOW + timedelta(days=30))

    await store.revoke(created.id, revoked_at=_NOW)

    refetched = await store.get_by_id(tenant_id, created.id)
    assert refetched.revoked_at == _NOW


async def test_revoke_all_for_user_only_touches_that_users_sessions(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    user_a = await make_user(db_conn, tenant_id, site_id, role="reception")
    user_b = await make_user(db_conn, tenant_id, site_id, role="reception")
    store = PostgresSessionStore(db_conn)
    session_a1 = await store.create(tenant_id, user_a, refresh_token_hash="a1", expires_at=_NOW + timedelta(days=30))
    session_a2 = await store.create(tenant_id, user_a, refresh_token_hash="a2", expires_at=_NOW + timedelta(days=30))
    session_b = await store.create(tenant_id, user_b, refresh_token_hash="b1", expires_at=_NOW + timedelta(days=30))

    revoked_count = await store.revoke_all_for_user(tenant_id, user_a, revoked_at=_NOW)

    assert revoked_count == 2
    assert (await store.get_by_id(tenant_id, session_a1.id)).revoked_at == _NOW
    assert (await store.get_by_id(tenant_id, session_a2.id)).revoked_at == _NOW
    assert (await store.get_by_id(tenant_id, session_b.id)).revoked_at is None


async def test_revoke_chain_revokes_every_session_in_the_rotation_lineage(db_conn, tenant_id) -> None:
    user_id = await _make_user(db_conn, tenant_id)
    store = PostgresSessionStore(db_conn)
    gen1 = await store.create(tenant_id, user_id, refresh_token_hash="g1", expires_at=_NOW + timedelta(days=30))
    gen2 = await store.create(
        tenant_id, user_id, refresh_token_hash="g2", expires_at=_NOW + timedelta(days=30), rotated_from=gen1.id
    )
    gen3 = await store.create(
        tenant_id, user_id, refresh_token_hash="g3", expires_at=_NOW + timedelta(days=30), rotated_from=gen2.id
    )
    unrelated = await store.create(tenant_id, user_id, refresh_token_hash="u1", expires_at=_NOW + timedelta(days=30))

    # Reuse of gen1 (the OLDEST token in the chain) must revoke the WHOLE
    # lineage -- gen2 and gen3 too, not just gen1 itself.
    await store.revoke_chain(gen1.id, revoked_at=_NOW)

    assert (await store.get_by_id(tenant_id, gen1.id)).revoked_at == _NOW
    assert (await store.get_by_id(tenant_id, gen2.id)).revoked_at == _NOW
    assert (await store.get_by_id(tenant_id, gen3.id)).revoked_at == _NOW
    assert (await store.get_by_id(tenant_id, unrelated.id)).revoked_at is None


async def test_find_successor_returns_none_when_no_rotation_happened(db_conn, tenant_id) -> None:
    user_id = await _make_user(db_conn, tenant_id)
    store = PostgresSessionStore(db_conn)
    session = await store.create(tenant_id, user_id, refresh_token_hash="solo", expires_at=_NOW + timedelta(days=30))

    assert await store.find_successor(session.id) is None


async def test_find_successor_returns_the_rotated_child_session(db_conn, tenant_id) -> None:
    user_id = await _make_user(db_conn, tenant_id)
    store = PostgresSessionStore(db_conn)
    parent = await store.create(tenant_id, user_id, refresh_token_hash="parent", expires_at=_NOW + timedelta(days=30))
    child = await store.create(
        tenant_id, user_id, refresh_token_hash="child", expires_at=_NOW + timedelta(days=30), rotated_from=parent.id
    )

    successor = await store.find_successor(parent.id)
    assert successor is not None
    assert successor.id == child.id


async def test_rotate_revokes_the_old_session_and_creates_its_successor_in_one_call(db_conn, tenant_id) -> None:
    user_id = await _make_user(db_conn, tenant_id)
    store = PostgresSessionStore(db_conn)
    old_session = await store.create(
        tenant_id, user_id, refresh_token_hash="old-hash", expires_at=_NOW + timedelta(days=30)
    )

    successor = await store.rotate(
        old_session.id,
        tenant_id,
        user_id,
        refresh_token_hash="new-hash",
        expires_at=_NOW + timedelta(days=30),
        revoked_at=_NOW,
    )

    assert successor.rotated_from == old_session.id
    assert successor.refresh_token_hash == "new-hash"
    refetched_old = await store.get_by_id(tenant_id, old_session.id)
    assert refetched_old.revoked_at == _NOW
    found_successor = await store.find_successor(old_session.id)
    assert found_successor is not None
    assert found_successor.id == successor.id


async def test_revoke_chain_from_a_middle_generation_also_reaches_ancestors_and_descendants(db_conn, tenant_id) -> None:
    user_id = await _make_user(db_conn, tenant_id)
    store = PostgresSessionStore(db_conn)
    gen1 = await store.create(tenant_id, user_id, refresh_token_hash="m1", expires_at=_NOW + timedelta(days=30))
    gen2 = await store.create(
        tenant_id, user_id, refresh_token_hash="m2", expires_at=_NOW + timedelta(days=30), rotated_from=gen1.id
    )
    gen3 = await store.create(
        tenant_id, user_id, refresh_token_hash="m3", expires_at=_NOW + timedelta(days=30), rotated_from=gen2.id
    )

    await store.revoke_chain(gen2.id, revoked_at=_NOW)

    assert (await store.get_by_id(tenant_id, gen1.id)).revoked_at == _NOW
    assert (await store.get_by_id(tenant_id, gen2.id)).revoked_at == _NOW
    assert (await store.get_by_id(tenant_id, gen3.id)).revoked_at == _NOW
