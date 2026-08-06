import pytest

from app.modules.governance.rbac.adapters.outbound.rbac.action_catalog import seed_action_catalog
from app.modules.governance.rbac.adapters.outbound.rbac.default_role_permissions import (
    DEFAULT_DEV_ROLE_PERMISSIONS,
    seed_default_role_permissions,
)
from app.modules.governance.rbac.adapters.outbound.rbac.permission_service import PermissionService
from app.modules.governance.rbac.application.use_cases.authorize_action import (
    ActionNotPermittedError,
    AuthorizeAction,
)
from app.shared_kernel.tenant_context import TenantContext
from tests.rls.helpers import seed_tenant, set_app_context


async def test_seeded_matrix_allows_a_granted_action_for_its_role(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    await seed_action_catalog(rls_conn)
    # `role_permissions` IS tenant-scoped RLS  -- the write
    # needs `app.tenant_id` set, though any role may write (the tenant-only
    # policy, tests/rls/test_rbac_permissions_rls.py).
    await set_app_context(rls_conn, tenant_id=tenant_id, role="admin")
    await seed_default_role_permissions(rls_conn, tenant_id)

    granted_action = DEFAULT_DEV_ROLE_PERMISSIONS["reception"][0]
    await set_app_context(rls_conn, tenant_id=tenant_id, role="reception")
    authorize = AuthorizeAction(PermissionService(rls_conn))

    # Must not raise -- the placeholder grant resolves to allowed=True.
    await authorize.execute(TenantContext(tenant_id=tenant_id, role="reception"), action=granted_action)


async def test_seeded_matrix_denies_an_ungranted_action_for_its_role(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    await seed_action_catalog(rls_conn)
    await set_app_context(rls_conn, tenant_id=tenant_id, role="admin")
    await seed_default_role_permissions(rls_conn, tenant_id)

    assert "staff:register" not in DEFAULT_DEV_ROLE_PERMISSIONS["patient"]
    await set_app_context(rls_conn, tenant_id=tenant_id, role="patient")
    authorize = AuthorizeAction(PermissionService(rls_conn))

    with pytest.raises(ActionNotPermittedError):
        await authorize.execute(TenantContext(tenant_id=tenant_id, role="patient"), action="staff:register")
