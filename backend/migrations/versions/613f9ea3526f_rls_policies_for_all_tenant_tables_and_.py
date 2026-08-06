"""Enable FORCE RLS and policies on tenant tables; grant app_runtime.

app_user is the bootstrap superuser (BYPASSRLS); policies only bind on
app_runtime. No RLS on tenants, action_permissions, or rate_counters.
GUC unset raises; empty string is not a valid uuid cast — use a sentinel
nil UUID for unused app.* settings. INSERT...RETURNING needs a matching
SELECT policy (audit_logs_actor_select). Staff policies on patients/
consents allow site_id IS NULL (tenant-wide until assigned).

Revision ID: 613f9ea3526f
Revises: 7441c553c450
Create Date: 2026-07-13 11:44:58.590185

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '613f9ea3526f'
down_revision: Union[str, Sequence[str], None] = '7441c553c450'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tables enabling RLS with the generic "tenant (+site+role)" shape, i.e.
# everything except patients/consents/calendar_credentials (tenant-wide self
# policy) and the explicitly-excluded tenants/action_permissions/rate_counters.
_RLS_TABLES = (
    "sites",
    "professionals",
    "users",
    "patients",
    "availability",
    "appointments",
    "consent_policies",
    "consents",
    "audit_logs",
    "role_permissions",
    "user_permissions",
    "staff_members",
    "shifts",
    "calendar_credentials",
    "calendar_sync",
    "user_sessions",
)


def upgrade() -> None:
    """Upgrade schema."""
    # --- app_runtime grants (the blocker fix) -------------------------------
    # `GRANT USAGE ON SCHEMA public` is re-issued here (not left to
    # infra/postgres/init/02_app_runtime_role.sql alone): the test harness
    # (tests/conftest.py `_migrated_schema`) does `DROP SCHEMA public CASCADE`
    # + `CREATE SCHEMA public` once per test session to reset state -- a
    # freshly `CREATE SCHEMA`'d namespace is a brand-new object with no ACL
    # entries (schema-level grants are tied to the specific namespace OID,
    # not the name), so the one-time init-script grant against the
    # *original* public schema does not carry over. Re-granting here, inside
    # a migration that re-runs on every reset, is what actually keeps
    # `app_runtime` able to connect after a schema reset in dev/test; in a
    # real deployment (schema never dropped) this GRANT is simply a no-op
    # repeat of the init script's.
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime') THEN
            GRANT USAGE ON SCHEMA public TO app_runtime;
            GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_runtime;
            ALTER DEFAULT PRIVILEGES FOR ROLE app_user IN SCHEMA public
              GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_runtime;
            REVOKE UPDATE, DELETE, TRUNCATE ON audit_logs FROM app_runtime;
          END IF;
        END $$;
        """
    )

    for table in _RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    # --- sites: shared reference data, admin-only write ---------------------
    op.execute(
        """
        CREATE POLICY sites_select ON sites FOR SELECT
          USING (current_setting('app.tenant_id')::uuid = tenant_id)
        """
    )
    op.execute(
        """
        CREATE POLICY sites_admin_write ON sites FOR ALL
          USING (current_setting('app.tenant_id')::uuid = tenant_id
                 AND current_setting('app.role') = 'admin')
        """
    )

    # --- professionals: shared reference data, admin-only write ------------
    op.execute(
        """
        CREATE POLICY professionals_select ON professionals FOR SELECT
          USING (current_setting('app.tenant_id')::uuid = tenant_id
                 AND current_setting('app.site_id')::uuid = site_id)
        """
    )
    op.execute(
        """
        CREATE POLICY professionals_admin_write ON professionals FOR ALL
          USING (current_setting('app.tenant_id')::uuid = tenant_id
                 AND current_setting('app.site_id')::uuid = site_id
                 AND current_setting('app.role') = 'admin')
        """
    )

    # --- users: self-visibility + staff directory, admin-only write --------
    op.execute(
        """
        CREATE POLICY users_self_select ON users FOR SELECT
          USING (current_setting('app.tenant_id')::uuid = tenant_id
                 AND current_setting('app.user_id')::uuid = id)
        """
    )
    op.execute(
        """
        CREATE POLICY users_staff_select ON users FOR SELECT
          USING (current_setting('app.tenant_id')::uuid = tenant_id
                 AND current_setting('app.site_id')::uuid = site_id
                 AND current_setting('app.role') IN ('reception', 'admin'))
        """
    )
    op.execute(
        """
        CREATE POLICY users_admin_write ON users FOR ALL
          USING (current_setting('app.tenant_id')::uuid = tenant_id
                 AND current_setting('app.site_id')::uuid = site_id
                 AND current_setting('app.role') = 'admin')
        """
    )

    # --- patients -----------------------------------------------------------
    op.execute(
        """
        CREATE POLICY patients_staff ON patients FOR ALL
          USING (current_setting('app.tenant_id')::uuid = tenant_id
                 AND current_setting('app.role') IN ('reception', 'professional', 'admin')
                 AND (site_id = current_setting('app.site_id')::uuid OR site_id IS NULL))
        """
    )
    op.execute(
        """
        CREATE POLICY patients_self ON patients FOR SELECT
          USING (current_setting('app.tenant_id')::uuid = tenant_id
                 AND current_setting('app.role') = 'patient'
                 AND id = current_setting('app.patient_id')::uuid)
        """
    )

    # --- availability: reception/admin site-wide; professional own slots ---
    op.execute(
        """
        CREATE POLICY availability_reception ON availability FOR ALL
          USING (current_setting('app.tenant_id')::uuid = tenant_id
                 AND current_setting('app.role') IN ('reception', 'admin')
                 AND current_setting('app.site_id')::uuid = site_id)
        """
    )
    op.execute(
        """
        CREATE POLICY availability_professional ON availability FOR ALL
          USING (current_setting('app.tenant_id')::uuid = tenant_id
                 AND current_setting('app.role') = 'professional'
                 AND current_setting('app.site_id')::uuid = site_id
                 AND current_setting('app.professional_id')::uuid = professional_id)
        """
    )

    # --- appointments -------------------------------------------------------
    op.execute(
        """
        CREATE POLICY appointments_reception ON appointments FOR ALL
          USING (current_setting('app.tenant_id')::uuid = tenant_id
                 AND current_setting('app.role') = 'reception'
                 AND current_setting('app.site_id')::uuid = site_id)
        """
    )
    op.execute(
        """
        CREATE POLICY appointments_professional ON appointments FOR ALL
          USING (current_setting('app.tenant_id')::uuid = tenant_id
                 AND current_setting('app.role') = 'professional'
                 AND current_setting('app.site_id')::uuid = site_id
                 AND current_setting('app.professional_id')::uuid = professional_id)
        """
    )
    op.execute(
        """
        CREATE POLICY appointments_patient_select ON appointments FOR SELECT
          USING (current_setting('app.tenant_id')::uuid = tenant_id
                 AND current_setting('app.role') = 'patient'
                 AND current_setting('app.patient_id')::uuid = patient_id)
        """
    )

    # --- consent_policies: shared reference data, admin-only write ---------
    op.execute(
        """
        CREATE POLICY consent_policies_select ON consent_policies FOR SELECT
          USING (current_setting('app.tenant_id')::uuid = tenant_id)
        """
    )
    op.execute(
        """
        CREATE POLICY consent_policies_admin_write ON consent_policies FOR ALL
          USING (current_setting('app.tenant_id')::uuid = tenant_id
                 AND current_setting('app.role') = 'admin')
        """
    )

    # --- consents: same shape as patients (tenant-wide self + staff) -------
    op.execute(
        """
        CREATE POLICY consents_staff ON consents FOR ALL
          USING (current_setting('app.tenant_id')::uuid = tenant_id
                 AND current_setting('app.role') IN ('reception', 'professional', 'admin')
                 AND (current_setting('app.site_id')::uuid = site_id OR site_id IS NULL))
        """
    )
    op.execute(
        """
        CREATE POLICY consents_patient_select ON consents FOR SELECT
          USING (current_setting('app.tenant_id')::uuid = tenant_id
                 AND current_setting('app.role') = 'patient'
                 AND current_setting('app.patient_id')::uuid = patient_id)
        """
    )

    # --- audit_logs: any role writes its own trail; only admin reads -------
    op.execute(
        """
        CREATE POLICY audit_logs_insert ON audit_logs FOR INSERT
          WITH CHECK (current_setting('app.tenant_id')::uuid = tenant_id)
        """
    )
    op.execute(
        """
        CREATE POLICY audit_logs_admin_select ON audit_logs FOR SELECT
          USING (current_setting('app.tenant_id')::uuid = tenant_id
                 AND current_setting('app.role') = 'admin')
        """
    )
    op.execute(
        """
        CREATE POLICY audit_logs_actor_select ON audit_logs FOR SELECT
          USING (current_setting('app.tenant_id')::uuid = tenant_id
                 AND (actor_id = current_setting('app.user_id')::uuid
                      OR (actor_type = 'system' AND actor_id IS NULL)))
        """
    )

    # --- role_permissions / user_permissions: tenant-only (no site_id) ------
    op.execute(
        """
        CREATE POLICY role_permissions_tenant ON role_permissions FOR ALL
          USING (current_setting('app.tenant_id')::uuid = tenant_id)
        """
    )
    op.execute(
        """
        CREATE POLICY user_permissions_tenant ON user_permissions FOR ALL
          USING (current_setting('app.tenant_id')::uuid = tenant_id)
        """
    )

    # --- staff_members: reception/admin manage; a professional sees their
    # own staff record (needed to resolve their own shifts) -----------------
    op.execute(
        """
        CREATE POLICY staff_members_staff ON staff_members FOR ALL
          USING (current_setting('app.tenant_id')::uuid = tenant_id
                 AND current_setting('app.site_id')::uuid = site_id
                 AND current_setting('app.role') IN ('reception', 'admin'))
        """
    )
    op.execute(
        """
        CREATE POLICY staff_members_self_select ON staff_members FOR SELECT
          USING (current_setting('app.tenant_id')::uuid = tenant_id
                 AND current_setting('app.role') = 'professional'
                 AND professional_id = current_setting('app.professional_id')::uuid)
        """
    )

    # --- shifts: reception/admin manage; a professional sees their own -----
    op.execute(
        """
        CREATE POLICY shifts_staff ON shifts FOR ALL
          USING (current_setting('app.tenant_id')::uuid = tenant_id
                 AND current_setting('app.site_id')::uuid = site_id
                 AND current_setting('app.role') IN ('reception', 'admin'))
        """
    )
    op.execute(
        """
        CREATE POLICY shifts_professional_select ON shifts FOR SELECT
          USING (current_setting('app.tenant_id')::uuid = tenant_id
                 AND current_setting('app.site_id')::uuid = site_id
                 AND current_setting('app.role') = 'professional'
                 AND EXISTS (
                   SELECT 1 FROM staff_members sm
                   WHERE sm.id = shifts.staff_member_id
                     AND sm.professional_id = current_setting('app.professional_id')::uuid
                 ))
        """
    )

    # --- calendar_credentials: patient-self only ----------------------------
    op.execute(
        """
        CREATE POLICY calendar_credentials_self ON calendar_credentials FOR ALL
          USING (current_setting('app.tenant_id')::uuid = tenant_id
                 AND current_setting('app.role') = 'patient'
                 AND patient_id = current_setting('app.patient_id')::uuid)
        """
    )

    # --- calendar_sync: tenant+site+role, staff only ------------------------
    op.execute(
        """
        CREATE POLICY calendar_sync_staff ON calendar_sync FOR ALL
          USING (current_setting('app.tenant_id')::uuid = tenant_id
                 AND current_setting('app.site_id')::uuid = site_id
                 AND current_setting('app.role') IN ('reception', 'professional', 'admin'))
        """
    )

    # --- user_sessions: tenant-only (system-tier access path) ---------------
    # Enforces tenant boundary only — not per-user isolation. Safe only if
    # queried via elevated/system path, never a per-role domain endpoint.
    op.execute(
        """
        CREATE POLICY user_sessions_tenant ON user_sessions FOR ALL
          USING (current_setting('app.tenant_id')::uuid = tenant_id)
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    policies = {
        "sites": ["sites_select", "sites_admin_write"],
        "professionals": ["professionals_select", "professionals_admin_write"],
        "users": ["users_self_select", "users_staff_select", "users_admin_write"],
        "patients": ["patients_staff", "patients_self"],
        "availability": ["availability_reception", "availability_professional"],
        "appointments": [
            "appointments_reception",
            "appointments_professional",
            "appointments_patient_select",
        ],
        "consent_policies": ["consent_policies_select", "consent_policies_admin_write"],
        "consents": ["consents_staff", "consents_patient_select"],
        "audit_logs": ["audit_logs_insert", "audit_logs_admin_select", "audit_logs_actor_select"],
        "role_permissions": ["role_permissions_tenant"],
        "user_permissions": ["user_permissions_tenant"],
        "staff_members": ["staff_members_staff", "staff_members_self_select"],
        "shifts": ["shifts_staff", "shifts_professional_select"],
        "calendar_credentials": ["calendar_credentials_self"],
        "calendar_sync": ["calendar_sync_staff"],
        "user_sessions": ["user_sessions_tenant"],
    }
    for table, policy_names in policies.items():
        for policy in policy_names:
            op.execute(f"DROP POLICY {policy} ON {table}")

    for table in reversed(_RLS_TABLES):
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime') THEN
            GRANT UPDATE, DELETE, TRUNCATE ON audit_logs TO app_runtime;
            ALTER DEFAULT PRIVILEGES FOR ROLE app_user IN SCHEMA public
              REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM app_runtime;
            REVOKE SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public FROM app_runtime;
          END IF;
        END $$;
        """
    )
