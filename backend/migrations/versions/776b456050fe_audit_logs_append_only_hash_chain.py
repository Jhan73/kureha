"""audit_logs append only hash chain

Task 2.4 (openspec/changes/kureha-mvp/tasks.md, Phase 2). Schema + triggers
per design.md §4.3. Two independent defenses, both created here:

1. Permission layer (`REVOKE`/`GRANT`): `app_user` can only INSERT/SELECT.
   NOTE (deviation, flagged): in the current local/dev setup `app_user` is
   the Postgres bootstrap superuser (see docker-compose.yml POSTGRES_USER)
   and therefore bypasses GRANT/REVOKE entirely -- this layer is presently a
   no-op locally and only takes effect once a properly restricted `app_user`
   role (design.md §4.2: "sin BYPASSRLS") is introduced. Flagged as a risk
   for the RLS work unit (task 2.9+), not fixed here (out of this task's
   scope, and superuser role provisioning is infra, not a Postgres schema
   migration concern).
2. Trigger layer (`trg_audit_no_update` + `trg_audit_no_truncate`): rejects
   UPDATE/DELETE/TRUNCATE unconditionally, regardless of role/privileges --
   this is what actually enforces append-only today, including against the
   superuser role above.
   NOTE (review fix, flagged not silently applied -- see apply-progress):
   `trg_audit_no_update` is `FOR EACH ROW`, and Postgres row-level triggers
   never fire on TRUNCATE -- the REVOKE naming TRUNCATE gave a false sense of
   coverage with no matching trigger-level defense. `trg_audit_no_truncate`
   (`FOR EACH STATEMENT`, reusing `audit_immutable()` since it only reads
   `TG_OP`, not `NEW`/`OLD`) closes that gap. Also, the REVOKE below now
   guards on the role existing (`DO $$ ... IF EXISTS ...`) so this migration
   does not hard-abort in an environment where `app_user` (docker-compose's
   `POSTGRES_USER`) is named differently -- the superuser-bypass caveat above
   is unchanged and still deferred to task 2.9+.

`digest()` (used by `audit_hash_chain()`) is provided by the `pgcrypto`
extension. design.md's §4.3 SQL sketch uses it without declaring where the
extension comes from; `pgcrypto` has been added to
`infra/postgres/init/01_extensions.sql` (same non-migration convention as
`btree_gist`, since `CREATE EXTENSION` needs superuser and app_user may not
have it on RDS) -- flagged as a design-doc gap filled here, not silently
assumed.

Revision ID: 776b456050fe
Revises: 5975cbe7665e
Create Date: 2026-07-13 10:14:28.070596

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '776b456050fe'
down_revision: Union[str, Sequence[str], None] = '5975cbe7665e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE TABLE audit_logs (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          seq bigint GENERATED ALWAYS AS IDENTITY,
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          site_id uuid REFERENCES sites(id),
          ts timestamptz NOT NULL DEFAULT now(),
          actor_id uuid,
          actor_type text NOT NULL CHECK (actor_type IN ('agent','user','system')),
          action text NOT NULL,
          object_type text NOT NULL,
          object_id uuid,
          reason text,
          approval_id uuid,
          payload jsonb NOT NULL DEFAULT '{}',
          prev_hash text,
          row_hash text NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX ix_audit_logs_chain ON audit_logs (tenant_id, seq)")
    op.execute(
        "CREATE INDEX ix_audit_logs_object ON audit_logs (tenant_id, object_type, object_id)"
    )

    # Layer 1: permissions (see module docstring for the current superuser
    # caveat and the role-existence guard below).
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
            REVOKE UPDATE, DELETE, TRUNCATE ON audit_logs FROM app_user;
            GRANT INSERT, SELECT ON audit_logs TO app_user;
          END IF;
        END $$
        """
    )

    # Layer 2: triggers that reject mutation unconditionally.
    op.execute(
        """
        CREATE FUNCTION audit_immutable() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'audit_logs is append-only (% not allowed)', TG_OP;
        END; $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_no_update BEFORE UPDATE OR DELETE ON audit_logs
          FOR EACH ROW EXECUTE FUNCTION audit_immutable()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_no_truncate BEFORE TRUNCATE ON audit_logs
          FOR EACH STATEMENT EXECUTE FUNCTION audit_immutable()
        """
    )

    # Hash-chain: each row references the previous row's hash within the
    # SAME tenant_id (ADR-8 -- the chain does not span tenants). The
    # advisory lock serializes concurrent inserts for a given tenant within
    # the transaction (released automatically at COMMIT/ROLLBACK).
    op.execute(
        """
        CREATE FUNCTION audit_hash_chain() RETURNS trigger AS $$
        DECLARE prev text;
        BEGIN
          PERFORM pg_advisory_xact_lock(hashtext(NEW.tenant_id::text));

          SELECT row_hash INTO prev
          FROM audit_logs
          WHERE tenant_id = NEW.tenant_id
          ORDER BY seq DESC LIMIT 1;

          NEW.prev_hash := prev;
          NEW.row_hash := encode(digest(
              coalesce(prev,'') || '|' ||
              NEW.tenant_id::text || '|' || NEW.actor_type || '|' || NEW.action || '|' ||
              coalesce(NEW.object_id::text,'') || '|' ||
              NEW.payload::text || '|' || NEW.ts::text,
              'sha256'), 'hex');
          RETURN NEW;
        END; $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_chain BEFORE INSERT ON audit_logs
          FOR EACH ROW EXECUTE FUNCTION audit_hash_chain()
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER trg_audit_chain ON audit_logs")
    op.execute("DROP FUNCTION audit_hash_chain()")
    op.execute("DROP TRIGGER trg_audit_no_truncate ON audit_logs")
    op.execute("DROP TRIGGER trg_audit_no_update ON audit_logs")
    op.execute("DROP FUNCTION audit_immutable()")
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
            GRANT UPDATE, DELETE, TRUNCATE ON audit_logs TO app_user;
          END IF;
        END $$
        """
    )
    op.execute("DROP INDEX ix_audit_logs_object")
    op.execute("DROP INDEX ix_audit_logs_chain")
    op.execute("DROP TABLE audit_logs")
