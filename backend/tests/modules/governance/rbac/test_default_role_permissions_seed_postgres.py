"""Task 3.6: `seed_default_role_permissions` -- placeholder, dev-only
role->action matrix seeded per tenant (design.md §16: the real
business-approved matrix is explicit "input de negocio pendiente"; this
mechanism only proves `AuthorizeAction` resolves correctly against seeded
data end-to-end against a real Postgres, never a fake `AuthorizationPort` --
the exact gap PR8's review found masked by `_FakeAuthorizationPort` in every
use-case-level test)."""

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
    # `role_permissions` IS tenant-scoped RLS (design.md §4.4) -- the write
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
