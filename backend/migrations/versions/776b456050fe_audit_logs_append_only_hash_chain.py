"""Add audit_logs with append-only triggers and per-tenant hash chain.

REVOKE/GRANT is no-op while app_user is the bootstrap superuser; row +
statement triggers enforce immutability. digest() needs pgcrypto
(infra/postgres/init). REVOKE is guarded with IF EXISTS on the role.

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

    # Per-tenant hash chain; advisory lock serializes concurrent inserts.
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
