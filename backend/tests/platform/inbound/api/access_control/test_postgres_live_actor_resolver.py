from tests.rls.helpers import seed_staff_member
from tests.schema.helpers import make_site, make_tenant, make_user

from app.platform.inbound.api.access_control.adapters.postgres_live_actor_resolver import (
    PostgresLiveActorResolver,
)


async def test_returns_none_when_no_users_row_matches(db_conn) -> None:
    resolver = PostgresLiveActorResolver(db_conn)
    assert await resolver.resolve("00000000-0000-0000-0000-000000000000") is None


async def test_resolves_a_patient_actor_with_no_staff_row(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    user_id = await make_user(db_conn, tenant_id, site_id, role="reception")

    resolver = PostgresLiveActorResolver(db_conn)
    actor = await resolver.resolve(user_id)

    assert actor is not None
    assert actor.user_id == user_id
    assert actor.tenant_id == tenant_id
    assert actor.site_id == site_id
    assert actor.role == "reception"
    assert actor.status == "active"
    assert actor.staff_status is None
    assert actor.is_active is True


async def test_resolves_a_staff_actor_with_an_active_staff_row(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    user_id = await make_user(db_conn, tenant_id, site_id, role="reception")
    await seed_staff_member(db_conn, tenant_id, site_id, operational_role="reception")
    # `seed_staff_member` does not accept `user_id` -- link it directly for this test.
    await db_conn.execute(
        __import__("sqlalchemy").text(
            "UPDATE staff_members SET user_id = :user_id WHERE tenant_id = :tenant_id AND user_id IS NULL"
        ),
        {"user_id": user_id, "tenant_id": tenant_id},
    )

    resolver = PostgresLiveActorResolver(db_conn)
    actor = await resolver.resolve(user_id)

    assert actor is not None
    assert actor.staff_status == "active"
    assert actor.is_active is True


async def test_resolves_a_staff_actor_with_an_inactive_staff_row(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    user_id = await make_user(db_conn, tenant_id, site_id, role="reception")
    await seed_staff_member(db_conn, tenant_id, site_id, operational_role="reception")
    await db_conn.execute(
        __import__("sqlalchemy").text(
            "UPDATE staff_members SET user_id = :user_id, status = 'inactive' "
            "WHERE tenant_id = :tenant_id AND user_id IS NULL"
        ),
        {"user_id": user_id, "tenant_id": tenant_id},
    )

    resolver = PostgresLiveActorResolver(db_conn)
    actor = await resolver.resolve(user_id)

    assert actor is not None
    assert actor.staff_status == "inactive"
    assert actor.is_active is False


async def test_resolves_an_inactive_users_row(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    user_id = await make_user(db_conn, tenant_id, site_id, role="reception")
    await db_conn.execute(
        __import__("sqlalchemy").text("UPDATE users SET status = 'inactive' WHERE id = :id"),
        {"id": user_id},
    )

    resolver = PostgresLiveActorResolver(db_conn)
    actor = await resolver.resolve(user_id)

    assert actor is not None
    assert actor.status == "inactive"
    assert actor.is_active is False


async def test_resolves_by_id_alone_across_tenants(db_conn) -> None:
    tenant_a = await make_tenant(db_conn)
    tenant_b = await make_tenant(db_conn)
    site_a = await make_site(db_conn, tenant_a)
    site_b = await make_site(db_conn, tenant_b)
    user_a = await make_user(db_conn, tenant_a, site_a, role="admin")
    user_b = await make_user(db_conn, tenant_b, site_b, role="admin")

    resolver = PostgresLiveActorResolver(db_conn)
    actor_a = await resolver.resolve(user_a)
    actor_b = await resolver.resolve(user_b)

    assert actor_a.tenant_id == tenant_a
    assert actor_b.tenant_id == tenant_b
