"""langgraph checkpointer tables and rls via thread_id tenant prefix

Task 2.10 (openspec/changes/kureha-mvp/tasks.md, Phase 2). Schema per
design.md §4.4/§8.6.

**Why `PostgresSaver.setup()` (sync), not `AsyncPostgresSaver.setup()`
(async), and why it runs against its OWN connection instead of Alembic's:**
Alembic's `run_migrations_online()` (migrations/env.py) already runs inside
`asyncio.run(run_async_migrations())`, and `do_run_migrations()` (where every
`upgrade()` executes) runs via `AsyncConnection.run_sync(...)`, which uses
SQLAlchemy's greenlet trick to let synchronous code call back into the same
already-running event loop. Calling `asyncio.run()` (or
`loop.run_until_complete()`) again from inside `upgrade()` to drive
`AsyncPostgresSaver.setup()` would raise "cannot be called from a running
event loop" -- there is no clean way to await async code from here.
`PostgresSaver` (the sync twin of `AsyncPostgresSaver`, sharing the exact
same `MIGRATIONS` DDL list in `langgraph.checkpoint.postgres.base`) sidesteps
this entirely: it opens its own plain synchronous `psycopg` connection
(autocommit) and runs its own idempotent internal migration tracking
(`checkpoint_migrations`), completely independent of Alembic's connection/
transaction. This does mean the checkpointer's tables are NOT created inside
Alembic's own transaction for this revision (`PostgresSaver.setup()` always
autocommits its own DDL) -- acceptable since `.setup()` is itself idempotent
and safe to invoke more than once.

**Why `checkpoint_blobs` gets RLS too, though design.md's §4.4 snippet only
names `checkpoints`/`checkpoint_writes` explicitly:** `checkpoint_blobs` also
carries a `thread_id` column and stores the actual channel value blobs (i.e.
conversation/graph state, potentially sensitive) -- omitting it would leave
a real PII-bearing table with no tenant isolation. `checkpoint_migrations`
does NOT get RLS: it has no `thread_id` (or any tenant-identifying column)
at all, it is pure internal version bookkeeping for the saver itself.

**Atomicity fix (found in review):** since `saver.setup()` autocommits the
table creation on its own connection outside Alembic's transaction, the
`ENABLE`/`FORCE ROW LEVEL SECURITY` + `CREATE POLICY` statements below run on
THAT SAME `saver.conn` psycopg connection (via a plain cursor, autocommitting
each statement immediately), not via Alembic's `op.execute()`. If they ran
inside Alembic's transaction instead, a LATER migration failing in the same
`alembic upgrade head` invocation would roll back the RLS-enabling
statements while the already-externally-committed checkpoint tables (and any
data written to them since) survived without RLS -- a real window for a
PII-bearing table, not a hypothetical one, since running several pending
migrations in one invocation is the normal deploy pattern. Coupling both to
`saver.conn` closes that window: either both commit (immediately, per
statement) or a failure here just leaves `.setup()`'s already-idempotent
migration tracking to redo the RLS statements too, since `CREATE POLICY`
would then fail on retry with "already exists" -- acceptable, since this
whole block is meant to be re-run to fixed-point like `.setup()` itself, and
a retry-after-partial-failure is caught immediately (not silently) via that
same "already exists" error.

RLS policy shape follows design.md §4.4/§8.6 literally: `thread_id` format is
`"{tenant_id}:{user_id}:{random}"`, so `split_part(thread_id, ':', 1)`
extracts the tenant_id directly.

Revision ID: 043b5dd9768e
Revises: 613f9ea3526f
Create Date: 2026-07-13 12:12:44.467043

"""
from typing import Sequence, Union

from alembic import op

from app.config import settings

# revision identifiers, used by Alembic.
revision: str = '043b5dd9768e'
down_revision: Union[str, Sequence[str], None] = '613f9ea3526f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RLS_TABLES = ("checkpoints", "checkpoint_writes", "checkpoint_blobs")


def _psycopg_dsn() -> str:
    # psycopg (unlike asyncpg) does not accept the `+asyncpg` driver suffix
    # SQLAlchemy's URL uses -- strip it down to the plain `postgresql://` scheme.
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


def upgrade() -> None:
    """Upgrade schema."""
    from langgraph.checkpoint.postgres import PostgresSaver

    with PostgresSaver.from_conn_string(_psycopg_dsn()) as saver:
        saver.setup()

        # Run on `saver.conn` (the same autocommitting connection `.setup()`
        # used), NOT `op.execute()` (Alembic's connection/transaction) -- see
        # the atomicity-fix note in this module's docstring.
        with saver.conn.cursor() as cur:
            for table in _RLS_TABLES:
                cur.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
                cur.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
                cur.execute(
                    f"""
                    CREATE POLICY {table}_tenant ON {table} FOR ALL
                      USING (split_part(thread_id, ':', 1)::uuid = current_setting('app.tenant_id')::uuid)
                    """
                )

            cur.execute(
                """
                DO $$
                BEGIN
                  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime') THEN
                    GRANT SELECT, INSERT, UPDATE, DELETE ON checkpoints, checkpoint_writes,
                      checkpoint_blobs, checkpoint_migrations TO app_runtime;
                  END IF;
                END $$;
                """
            )


def downgrade() -> None:
    """Downgrade schema."""
    for table in reversed(_RLS_TABLES):
        op.execute(f"DROP POLICY {table}_tenant ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.execute("DROP TABLE IF EXISTS checkpoint_writes")
    op.execute("DROP TABLE IF EXISTS checkpoint_blobs")
    op.execute("DROP TABLE IF EXISTS checkpoints")
    op.execute("DROP TABLE IF EXISTS checkpoint_migrations")
