"""Add LangGraph checkpointer tables with RLS on thread_id tenant prefix.

Uses sync PostgresSaver.setup() on its own connection (Alembic upgrade
already runs under asyncio.run; nested asyncio.run would fail). RLS also
covers checkpoint_blobs (has thread_id / state blobs). Policies run on the
same saver.conn so they commit with setup DDL, not inside Alembic's tx.
thread_id format is "{tenant_id}:{user_id}:{random}".

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
