"""rls policies for all tenant tables and app_runtime grants

Task 2.9 (openspec/changes/kureha-mvp/tasks.md, Phase 2). Schema per
design.md §4.2/§4.4. `ENABLE`+`FORCE ROW LEVEL SECURITY` on every table that
carries `tenant_id`, deny-by-default (a table with RLS enabled and zero
matching policies returns zero rows for every role except the owner).

BLOCKER FIXED HERE (flagged during PR 2's review): `app_user` (docker-compose
POSTGRES_USER) is the Postgres bootstrap superuser -- confirmed superuser +
BYPASSRLS (see infra/postgres/init/02_app_runtime_role.sql, tests/rls/). A
Postgres superuser unconditionally bypasses RLS regardless of `ENABLE`/
`FORCE`, so every policy below is meaningless against that role. This
migration's first block grants `app_runtime` (the restricted, non-superuser,
NOBYPASSRLS role created by that init script) the table privileges it needs;
every policy after that is only ever meaningfully enforced against
`app_runtime`. `app_user` keeps owning/migrating the schema (unchanged).

Design decisions NOT literally spelled out in design.md (flagged, not
silently invented -- recommend a design.md sync pass):

1. **`tenants` and `action_permissions` get NO RLS.** `tenants` does not
   itself carry a `tenant_id` column (its own `id` IS the tenant) and
   design.md never gives it a self-referential policy; `action_permissions`
   is explicitly documented as a global catalog with "sin RLS" (§4.4).
2. **`rate_counters` gets NO RLS**, per design.md §4.4's own text: nullable
   `tenant_id` (pre-login IP limit has none yet), touched only by the
   rate-limiting middleware (§19), never a domain use case or an
   authenticated-role query.
3. **`sites`/`professionals`/`users`/`consent_policies`/`audit_logs`** are
   NOT given an explicit per-role policy pattern anywhere in design.md
   (§4.2's worked example is `appointments`; §4.4 only assigns explicit
   patterns to `staff_members`/`shifts`/`calendar_sync`/`calendar_credentials`/
   `role_permissions`/`user_permissions`/`user_sessions`). For these five,
   this migration applies the narrowest defensible interpretation consistent
   with the surrounding design:
   - `sites`/`professionals`/`consent_policies`: any authenticated role in
     the tenant (+ site, for `professionals`) may SELECT (shared reference
     data, not PII); only `role='admin'` may INSERT/UPDATE/DELETE.
   - `users`: any role may SELECT its own row; `reception`/`admin` may
     SELECT the tenant+site's staff directory; only `role='admin'` may
     INSERT/UPDATE/DELETE. This does NOT resolve the identity-bootstrap
     "chicken-and-egg" problem design.md's §4.2 narrative implies (the
     initial `users` lookup by external `sub`, before `app.tenant_id`/
     `app.user_id` are known, must run through some system-tier/elevated
     path) -- that is Phase 4/5 (identity module) architecture, out of scope
     for a schema migration, and is called out here so it is not silently
     assumed solved.
   - `audit_logs`: INSERT is open to any role in the tenant (every use case
     must be able to write its own audit trail entry, regardless of actor
     role); SELECT is `role='admin'` (full tenant visibility) OR the row's
     own `actor_id` matches the caller (`app.user_id`) -- see point 7 below
     for why the actor-visibility policy exists at all. UPDATE/DELETE/
     TRUNCATE remain blocked for every role by the append-only trigger
     (776b456050fe) regardless of RLS.
4. **`calendar_credentials`** gets ONLY the patient-self policy design.md
   describes by analogy to `patients_self` -- no staff read/write policy is
   added (design.md doesn't specify one; Phase 9's OAuth callback flow will
   need to write this table through *some* context, which is an identity/
   calendar-module wiring question, not resolved here).
5. **GUC sentinel gap (found while writing this, NOT invented):** every
   policy uses the single-argument `current_setting('app.x')`, matching
   design.md §4.2's literal SQL. Postgres raises `unrecognized configuration
   parameter` if a GUC was NEVER set at all in the session -- and RLS
   evaluates every permissive policy applicable to a command (e.g.
   `patients_self`'s `app.patient_id` reference is evaluated even when the
   actor is `reception`, not `patient`), so ALL SIX GUCs from §4.2's
   `SET LOCAL` block must be set on every request, not just the ones
   relevant to the current actor's role -- confirming design.md's own
   "<uuid-or-empty>" comment on `patient_id`/`professional_id`. However a
   literal empty string is NOT a valid `::uuid` cast (`''::uuid` raises
   `invalid input syntax`), so "empty" must mean a sentinel UUID (this
   migration's tests use the nil UUID, `00000000-0000-0000-0000-000000000000`)
   -- Phase 5's access-control middleware (the real GUC emitter) needs to
   follow the same convention. Flagged here since getting it wrong breaks
   every query for every role, not just the one the missing GUC "belongs" to.
7. **RLS+RETURNING gotcha discovered while testing this migration (NOT in
   design.md, found empirically):** Postgres requires an `INSERT ...
   RETURNING` row to also satisfy an applicable SELECT policy -- if it
   doesn't, the whole INSERT fails with "new row violates row-level security
   policy", even though a plain `INSERT` (no RETURNING) of the exact same
   row succeeds. An `audit_logs` SELECT policy restricted to `role='admin'`
   alone would therefore break every non-admin-authored audit write that
   uses `RETURNING id` (the common case for getting the generated id back,
   e.g. to link `approval_id`) -- the insert would look like an RLS bug on
   the INSERT side when the real cause is the SELECT side. Fixed by adding
   `audit_logs_actor_select` (self-authored rows, via `actor_id =
   app.user_id`) alongside `audit_logs_admin_select` (full tenant
   visibility) -- any actor can always read back rows they themselves wrote,
   in addition to admins reading everything. Extended (found in review) to
   also match `actor_type = 'system' AND actor_id IS NULL` -- both nullable
   per 776b456050fe -- so a system-authored row (no human actor) written via
   `RETURNING id` from a non-admin connection hits the same gotcha this
   point exists to fix, not just human-actor rows.
8. Design.md gap found and RESOLVED here (flagged, not silently patched):
   the `patients_staff` policy from §4.2, copied verbatim (`site_id =
   current_setting('app.site_id')::uuid`), evaluates to `NULL` (never TRUE)
   for a row whose `site_id` is `NULL` -- which §4.1 explicitly allows
   ("site de registro (nullable, informativa)"). `consents_staff` has the
   identical shape and the identical gap (`consents.site_id` is equally
   nullable, per 5975cbe7665e). Both policies now add `OR site_id IS NULL`,
   so staff at ANY site within the tenant can see/write a record not yet
   assigned to a specific site -- the resolved default is "site-less records
   are tenant-wide staff-visible until assigned," not "invisible to
   everyone." Flagged for a design.md sync pass since this deviates from
   §4.2's literal SQL for both tables.

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

    # --- patients: design.md §4.2 literal SQL -------------------------------
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

    # --- availability: staff-managed slots (no patient policy -- browsing is
    # a Phase 7 read-model concern, not a raw-table RLS policy). Split into
    # the same reception/admin (site-wide) vs. professional (own slots only)
    # shape as `appointments` below -- design.md says availability follows
    # "el mismo patron" as appointments, and a single role-only policy let a
    # professional write another professional's slots at the same site
    # (found in review, fixed here). ------------------------------------
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

    # --- appointments: design.md §4.2 literal SQL ---------------------------
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

    # --- role_permissions / user_permissions: tenant-only (§4.4: "sin
    # site_id: los permisos aplican a todos los sites del tenant"); RBAC
    # (who may WRITE these) is a separate authorization plane (§5.1), not
    # encoded again at the RLS layer -----------------------------------------
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

    # --- calendar_credentials: tenant-wide self policy, same shape as
    # `patients_self` (design.md §4.4) --------------------------------------
    op.execute(
        """
        CREATE POLICY calendar_credentials_self ON calendar_credentials FOR ALL
          USING (current_setting('app.tenant_id')::uuid = tenant_id
                 AND current_setting('app.role') = 'patient'
                 AND patient_id = current_setting('app.patient_id')::uuid)
        """
    )

    # --- calendar_sync: tenant+site+role, staff only (§4.4) -----------------
    op.execute(
        """
        CREATE POLICY calendar_sync_staff ON calendar_sync FOR ALL
          USING (current_setting('app.tenant_id')::uuid = tenant_id
                 AND current_setting('app.site_id')::uuid = site_id
                 AND current_setting('app.role') IN ('reception', 'professional', 'admin'))
        """
    )

    # --- user_sessions: tenant-only (§4.4: "es tenant-scoped con RLS por
    # tenant" -- accessed by a system-tier stage, not per-role). INTENTIONALLY
    # broad (confirmed in review, not a gap): this policy enforces only the
    # tenant boundary, not per-user isolation -- any role in the tenant can
    # read every other user's session metadata (incl. `refresh_token_hash`,
    # a one-way hash, not a replayable secret). This is safe ONLY because the
    # invariant below must hold: only the system-tier session/refresh stage
    # (§17), which runs as `app_runtime` outside any per-role request path,
    # may query this table. NEVER wire `user_sessions` into a per-role
    # domain-facing query path (e.g. a "list my sessions" endpoint querying
    # this table directly) -- that would need its own `user_id`-scoped
    # policy, which does not exist here. -------------------------------
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
