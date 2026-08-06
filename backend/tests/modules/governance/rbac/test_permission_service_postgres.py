import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from app.modules.governance.rbac.adapters.outbound.rbac.permission_service import PermissionService
from app.shared_kernel.tenant_context import TenantContext
from tests.rls.helpers import seed_site, seed_tenant, seed_user, set_app_context


class _CountingConn:
    """Wraps an `AsyncConnection` to count `.execute()` calls -- duck-typed,
    `PermissionService` only ever calls `conn.execute(...)`."""

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn
        self.calls = 0

    async def execute(self, *args, **kwargs):
        self.calls += 1
        return await self._conn.execute(*args, **kwargs)


async def _seed_action(conn, key: str, *, tenant_id: str, role: str | None = None, allowed: bool | None = None) -> None:
    await conn.execute(
        sa.text("INSERT INTO action_permissions (key, description) VALUES (:key, 'x') ON CONFLICT DO NOTHING"),
        {"key": key},
    )
    if role is not None:
        await conn.execute(
            sa.text(
                "INSERT INTO role_permissions (tenant_id, role, action, allowed) "
                "VALUES (:t, :role, :key, :allowed)"
            ),
            {"t": tenant_id, "role": role, "key": key, "allowed": allowed},
        )


async def test_is_allowed_true_when_role_grants_and_no_override(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    user_id = await seed_user(rls_conn, tenant_id, site_id, role="reception")

    await set_app_context(rls_conn, tenant_id=tenant_id, role="admin")
    await _seed_action(rls_conn, "appointment:create", tenant_id=tenant_id, role="reception", allowed=True)

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception", user_id=user_id)
    service = PermissionService(rls_conn)
    ctx = TenantContext(tenant_id=tenant_id, role="reception", site_id=site_id, actor_id=user_id)

    assert await service.is_allowed(ctx, "appointment:create") is True


async def test_is_allowed_false_when_no_grant_at_all(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    await set_app_context(rls_conn, tenant_id=tenant_id, role="admin")
    await _seed_action(rls_conn, "staff:register", tenant_id=tenant_id)

    await set_app_context(rls_conn, tenant_id=tenant_id, role="reception")
    service = PermissionService(rls_conn)
    ctx = TenantContext(tenant_id=tenant_id, role="reception")

    assert await service.is_allowed(ctx, "staff:register") is False


async def test_user_override_deny_wins_over_role_allow(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    user_id = await seed_user(rls_conn, tenant_id, site_id, role="reception")

    await set_app_context(rls_conn, tenant_id=tenant_id, role="admin")
    await _seed_action(rls_conn, "appointment:cancel_bulk", tenant_id=tenant_id, role="reception", allowed=True)
    await rls_conn.execute(
        sa.text(
            "INSERT INTO user_permissions (tenant_id, user_id, action, allowed) "
            "VALUES (:t, :u, 'appointment:cancel_bulk', false)"
        ),
        {"t": tenant_id, "u": user_id},
    )

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception", user_id=user_id)
    service = PermissionService(rls_conn)
    ctx = TenantContext(tenant_id=tenant_id, role="reception", site_id=site_id, actor_id=user_id)

    assert await service.is_allowed(ctx, "appointment:cancel_bulk") is False


async def test_is_allowed_with_an_actor_issues_a_single_query(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    user_id = await seed_user(rls_conn, tenant_id, site_id, role="reception")

    await set_app_context(rls_conn, tenant_id=tenant_id, role="admin")
    await _seed_action(rls_conn, "appointment:create", tenant_id=tenant_id, role="reception", allowed=True)

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception", user_id=user_id)
    counting_conn = _CountingConn(rls_conn)
    service = PermissionService(counting_conn)
    ctx = TenantContext(tenant_id=tenant_id, role="reception", site_id=site_id, actor_id=user_id)

    assert await service.is_allowed(ctx, "appointment:create") is True
    assert counting_conn.calls == 1


async def test_is_allowed_memoizes_within_the_same_service_instance(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    await set_app_context(rls_conn, tenant_id=tenant_id, role="admin")
    await _seed_action(rls_conn, "appointment:view", tenant_id=tenant_id, role="reception", allowed=True)

    await set_app_context(rls_conn, tenant_id=tenant_id, role="reception")
    counting_conn = _CountingConn(rls_conn)
    service = PermissionService(counting_conn)
    ctx = TenantContext(tenant_id=tenant_id, role="reception")

    await service.is_allowed(ctx, "appointment:view")
    calls_after_first = counting_conn.calls
    await service.is_allowed(ctx, "appointment:view")

    assert calls_after_first > 0
    assert counting_conn.calls == calls_after_first  # second call served from memo, no new query


async def test_a_fresh_service_instance_never_sees_a_stale_memo(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    await set_app_context(rls_conn, tenant_id=tenant_id, role="admin")
    await _seed_action(rls_conn, "shift:create", tenant_id=tenant_id, role="reception", allowed=False)

    await set_app_context(rls_conn, tenant_id=tenant_id, role="reception")
    ctx = TenantContext(tenant_id=tenant_id, role="reception")
    first_service = PermissionService(rls_conn)
    assert await first_service.is_allowed(ctx, "shift:create") is False

    # Revoke flips to allow -- a NEW PermissionService instance (simulating
    # the next request) must see the update immediately, proving there is no
    # cache surviving across instances.
    await set_app_context(rls_conn, tenant_id=tenant_id, role="admin")
    await rls_conn.execute(
        sa.text("UPDATE role_permissions SET allowed = true WHERE tenant_id = :t AND action = 'shift:create'"),
        {"t": tenant_id},
    )

    await set_app_context(rls_conn, tenant_id=tenant_id, role="reception")
    second_service = PermissionService(rls_conn)
    assert await second_service.is_allowed(ctx, "shift:create") is True


async def test_list_allowed_actions_resolves_precedence_for_every_action_in_one_query(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    user_id = await seed_user(rls_conn, tenant_id, site_id, role="reception")

    await set_app_context(rls_conn, tenant_id=tenant_id, role="admin")
    await _seed_action(rls_conn, "appointment:view", tenant_id=tenant_id, role="reception", allowed=True)
    await _seed_action(rls_conn, "appointment:create", tenant_id=tenant_id, role="reception", allowed=True)
    await _seed_action(rls_conn, "staff:register", tenant_id=tenant_id, role="reception", allowed=False)
    await rls_conn.execute(
        sa.text(
            "INSERT INTO user_permissions (tenant_id, user_id, action, allowed) "
            "VALUES (:t, :u, 'appointment:create', false)"
        ),
        {"t": tenant_id, "u": user_id},
    )

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception", user_id=user_id)
    counting_conn = _CountingConn(rls_conn)
    service = PermissionService(counting_conn)
    ctx = TenantContext(tenant_id=tenant_id, role="reception", site_id=site_id, actor_id=user_id)

    allowed = await service.list_allowed_actions(ctx)

    assert allowed == {"appointment:view"}
    assert counting_conn.calls == 1  # single query resolves every action
