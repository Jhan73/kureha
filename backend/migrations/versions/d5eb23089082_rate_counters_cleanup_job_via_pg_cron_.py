"""rate_counters cleanup job via pg_cron when available

Task 2.11 (openspec/changes/kureha-mvp/tasks.md, Phase 2). Schema per
design.md §4.4: "Implementacion MVP: pg_cron ejecutado cada hora (o cada 6h)
en RDS PostgreSQL. Si pg_cron no esta disponible, una Lambda
CloudWatch-scheduled cada hora hace el mismo DELETE."

**Why this is guarded, not unconditional `CREATE EXTENSION pg_cron`:**
vanilla `postgres:16` (docker-compose.yml's local dev image) does not ship
`pg_cron` at all -- it needs to be compiled into the Postgres build and
loaded via `shared_preload_libraries` at server start (a cluster-level
setting, not something `CREATE EXTENSION` alone can retrofit), so an
unconditional `CREATE EXTENSION pg_cron` would hard-fail every local
`alembic upgrade head` and every test run. Guarding on
`pg_available_extensions` (which only lists extensions whose control files
exist on the filesystem -- i.e. genuinely compiled in) makes this migration
a safe no-op locally and a real schedule registration on RDS (where pg_cron
is an allow-listed extension, same tier as `pgcrypto`/`btree_gist` --
tasks.md task 16.1 already documents that RDS bootstrap step; this job's
extension enablement belongs alongside it when Phase 16 wires the real RDS
parameter group, not duplicated here).

**Fallback path (Lambda, design.md's alternative):** out of scope for this
schema-only migration -- Phase 16 (AWS deployment) task 16.2 already covers
EventBridge/ECS-scheduled jobs for the audit hash-chain verify job; a
CloudWatch-scheduled Lambda for this same DELETE, if pg_cron turns out to be
unavailable on the target RDS instance, is a Phase 16 infra decision, not
introduced here.

The cleanup query itself
(`DELETE FROM rate_counters WHERE window_start < now() - interval '24 hours'`)
is exactly the query already exercised in isolation by
`tests/schema/test_sessions_and_rate_limiting.py::test_rate_counter_cleanup_deletes_only_rows_older_than_24h`
(task 2.8) -- this migration only adds the *scheduling* of that same query.

Revision ID: d5eb23089082
Revises: 043b5dd9768e
Create Date: 2026-07-13 12:18:00.071066

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd5eb23089082'
down_revision: Union[str, Sequence[str], None] = '043b5dd9768e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CLEANUP_SQL = "DELETE FROM rate_counters WHERE window_start < now() - interval ''24 hours''"


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        f"""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'pg_cron') THEN
            CREATE EXTENSION IF NOT EXISTS pg_cron;
            PERFORM cron.schedule('rate_counters_cleanup', '0 * * * *', '{_CLEANUP_SQL}');
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'pg_cron')
             AND EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
            PERFORM cron.unschedule('rate_counters_cleanup');
          END IF;
        END $$;
        """
    )
