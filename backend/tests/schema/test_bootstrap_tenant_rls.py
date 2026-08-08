import uuid

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from app.modules.governance.audit.adapters.outbound.postgres.audit_log import PostgresAuditLog
from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.modules.governance.rbac.adapters.outbound.rbac.default_role_permissions import (
    DEFAULT_DEV_ROLE_PERMISSIONS,
)
from app.modules.governance.rbac.adapters.outbound.rbac.permission_service import PermissionService
from app.modules.governance.rbac.domain.permission import ActionKey
from app.modules.tenancy.adapters.outbound.postgres.tenant_provisioning_repository import (
    PostgresTenantProvisioningRepository,
)
from app.modules.tenancy.adapters.outbound.rbac.default_permissions_seeder import DefaultRolePermissionsSeeder
from app.shared_kernel.tenant_context import TenantContext
from tests.rls.helpers import seed_site, seed_tenant, set_app_context
from tests.schema.helpers import expect_violation

# Deny-by-default at mid-transaction (design.md ADR-02/§10): these three
# scenarios do not exercise new production code -- they characterize RLS
# policies already migrated in kureha-mvp Phase 2 (`613f9ea3526f`), proving
# the invariant `PostgresTenantProvisioningRepository` depends on for its
# safety argument (running the bootstrap on `app_runtime`, not a bypass
# connection). No production code drives these assertions; they document
# the pre-existing guarantee ahead of the new adapter's use of it.


async def test_users_insert_rejected_without_admin_role(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception")
    async with expect_violation(rls_conn, Exception, match="row-level security"):
        await rls_conn.execute(
            sa.text("INSERT INTO users (tenant_id, site_id, role) VALUES (:t, :s, 'admin')"),
            {"t": tenant_id, "s": site_id},
        )

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="admin")
    rows = (await rls_conn.execute(sa.text("SELECT id FROM users WHERE tenant_id = :t"), {"t": tenant_id})).all()
    assert rows == []


async def test_users_insert_rejected_with_mismatched_tenant_id(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    other_tenant_id = await seed_tenant(rls_conn)

    await set_app_context(rls_conn, tenant_id=other_tenant_id, site_id=site_id, role="admin")
    async with expect_violation(rls_conn, Exception, match="row-level security"):
        await rls_conn.execute(
            sa.text("INSERT INTO users (tenant_id, site_id, role) VALUES (:t, :s, 'admin')"),
            {"t": tenant_id, "s": site_id},
        )

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="admin")
    rows = (await rls_conn.execute(sa.text("SELECT id FROM users WHERE tenant_id = :t"), {"t": tenant_id})).all()
    assert rows == []


async def test_users_insert_rejected_with_mismatched_site_id(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id, name="Real Site")
    other_site_id = await seed_site(rls_conn, tenant_id, name="Other Site")

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=other_site_id, role="admin")
    async with expect_violation(rls_conn, Exception, match="row-level security"):
        await rls_conn.execute(
            sa.text("INSERT INTO users (tenant_id, site_id, role) VALUES (:t, :s, 'admin')"),
            {"t": tenant_id, "s": site_id},
        )

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="admin")
    rows = (await rls_conn.execute(sa.text("SELECT id FROM users WHERE tenant_id = :t"), {"t": tenant_id})).all()
    assert rows == []


async def test_bootstrap_sequence_rolls_back_when_audit_step_fails(rls_conn) -> None:
    """Mirrors the exact insert order `PostgresTenantProvisioningRepository`
    plus a caller's audit step would perform, then forces the last step
    (audit_logs) to fail via a CHECK violation -- the whole sequence must
    leave zero rows behind, proving nothing commits ahead of the audit
    trail the regulatory requirement depends on."""
    tenant_id = str(uuid.uuid4())
    site_id = str(uuid.uuid4())
    admin_user_id = str(uuid.uuid4())

    async with expect_violation(rls_conn, DBAPIError):
        await set_app_context(rls_conn, tenant_id=tenant_id, role="admin")
        await rls_conn.execute(
            sa.text("INSERT INTO tenants (id, name) VALUES (:id, 'Rollback Clinic')"),
            {"id": tenant_id},
        )
        await rls_conn.execute(
            sa.text("INSERT INTO sites (id, tenant_id, name) VALUES (:id, :t, 'Main Site')"),
            {"id": site_id, "t": tenant_id},
        )
        await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="admin")
        await rls_conn.execute(
            sa.text("INSERT INTO users (id, tenant_id, site_id, role) VALUES (:id, :t, :s, 'admin')"),
            {"id": admin_user_id, "t": tenant_id, "s": site_id},
        )
        await rls_conn.execute(
            sa.text(
                "INSERT INTO user_credentials (tenant_id, user_id, email) "
                "VALUES (:t, :u, 'admin@rollback-clinic.test')"
            ),
            {"t": tenant_id, "u": admin_user_id},
        )
        # Forced failure: audit_logs.actor_type CHECK constraint.
        await rls_conn.execute(
            sa.text(
                "INSERT INTO audit_logs (tenant_id, actor_type, action, object_type) "
                "VALUES (:t, 'bogus', 'tenant.bootstrap', 'tenant')"
            ),
            {"t": tenant_id},
        )

    # The savepoint rollback also reverts `SET LOCAL` GUCs set inside it
    # (back to unset) -- restore a valid context before reading anything
    # RLS-protected.
    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="admin")

    tenant_count = (
        await rls_conn.execute(sa.text("SELECT count(*) FROM tenants WHERE id = :t"), {"t": tenant_id})
    ).scalar_one()
    assert tenant_count == 0
    for table in ("sites", "users", "user_credentials"):
        count = (
            await rls_conn.execute(sa.text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"), {"t": tenant_id})
        ).scalar_one()
        assert count == 0


async def test_bootstrap_tenant_provisions_full_tenant_and_seeds_rbac(rls_conn) -> None:
    tenant_id = str(uuid.uuid4())
    site_id = str(uuid.uuid4())
    admin_user_id = str(uuid.uuid4())
    admin_email = "admin@integration-clinic.test"

    repo = PostgresTenantProvisioningRepository(rls_conn)
    seeder = DefaultRolePermissionsSeeder(rls_conn)
    audit_log = PostgresAuditLog(rls_conn)

    await repo.provision(
        tenant_id=tenant_id,
        name="Integration Clinic",
        site_id=site_id,
        site_name="Main Site",
        admin_user_id=admin_user_id,
        admin_email=admin_email,
    )
    await seeder.seed_for_tenant(tenant_id)
    audit_id = await audit_log.record(
        AuditEntry(
            tenant_id=tenant_id,
            actor_type=AuditActorType.SYSTEM,
            action=AuditAction.TENANT_BOOTSTRAP,
            object_type="tenant",
            object_id=tenant_id,
        )
    )

    tenants = (await rls_conn.execute(sa.text("SELECT id FROM tenants WHERE id = :t"), {"t": tenant_id})).all()
    assert [str(row.id) for row in tenants] == [tenant_id]

    sites = (await rls_conn.execute(sa.text("SELECT id FROM sites WHERE tenant_id = :t"), {"t": tenant_id})).all()
    assert [str(row.id) for row in sites] == [site_id]

    users = (
        await rls_conn.execute(sa.text("SELECT id, role FROM users WHERE tenant_id = :t"), {"t": tenant_id})
    ).all()
    assert len(users) == 1
    assert str(users[0].id) == admin_user_id
    assert users[0].role == "admin"

    credentials = (
        await rls_conn.execute(
            sa.text("SELECT id, email, auth_subject FROM user_credentials WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
    ).all()
    assert len(credentials) == 1
    assert credentials[0].email == admin_email
    assert credentials[0].auth_subject is None

    role_permissions = (
        await rls_conn.execute(
            sa.text("SELECT action FROM role_permissions WHERE tenant_id = :t AND role = 'admin'"),
            {"t": tenant_id},
        )
    ).all()
    assert len(role_permissions) == len(DEFAULT_DEV_ROLE_PERMISSIONS["admin"])

    audit_rows = (
        await rls_conn.execute(
            sa.text("SELECT id, prev_hash, action FROM audit_logs WHERE tenant_id = :t"), {"t": tenant_id}
        )
    ).all()
    assert len(audit_rows) == 1
    assert str(audit_rows[0].id) == audit_id
    assert audit_rows[0].prev_hash is None
    assert audit_rows[0].action == "tenant.bootstrap"

    # The freshly seeded role_permissions row resolves an allowed action
    # immediately, in this same process/transaction -- no restart needed.
    permission_service = PermissionService(rls_conn)
    ctx = TenantContext(tenant_id=tenant_id, role="admin", site_id=site_id, actor_id=admin_user_id)
    assert await permission_service.is_allowed(ctx, ActionKey("appointment:create")) is True
