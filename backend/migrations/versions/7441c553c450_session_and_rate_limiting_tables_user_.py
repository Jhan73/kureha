"""Add user_sessions and rate_counters tables.

rate_counters has no RLS (nullable tenant_id for pre-login IP limits).
Index on window_start is non-partial: now() is not IMMUTABLE so a partial
predicate `WHERE window_start < now() - interval '24 hours'` is rejected.
Composite FKs keep session rotation chains within a tenant.

Revision ID: 7441c553c450
Revises: 00d985a7bfa5
Create Date: 2026-07-13 11:40:28.809920

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7441c553c450'
down_revision: Union[str, Sequence[str], None] = '00d985a7bfa5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "ALTER TABLE tenants ADD COLUMN llm_daily_budget_tokens int NOT NULL DEFAULT 100000"
    )

    op.execute(
        """
        CREATE TABLE user_sessions (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          user_id uuid NOT NULL,
          refresh_token_hash text NOT NULL,
          issued_at timestamptz NOT NULL DEFAULT now(),
          expires_at timestamptz NOT NULL,
          rotated_from uuid,
          revoked_at timestamptz,
          last_used_at timestamptz,
          FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id, id),
          FOREIGN KEY (tenant_id, rotated_from) REFERENCES user_sessions (tenant_id, id),
          UNIQUE (tenant_id, id),
          UNIQUE (tenant_id, refresh_token_hash)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_user_sessions_active ON user_sessions (tenant_id, user_id) "
        "WHERE revoked_at IS NULL"
    )

    op.execute(
        """
        CREATE TABLE rate_counters (
          tenant_id uuid,
          dimension text NOT NULL,
          subject text NOT NULL,
          window_start timestamptz NOT NULL,
          count int NOT NULL DEFAULT 0,
          PRIMARY KEY (dimension, subject, window_start)
        )
        """
    )
    op.execute("CREATE INDEX ix_rate_counters_window ON rate_counters (window_start)")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX ix_rate_counters_window")
    op.execute("DROP TABLE rate_counters")
    op.execute("DROP INDEX ix_user_sessions_active")
    op.execute("DROP TABLE user_sessions")
    op.execute("ALTER TABLE tenants DROP COLUMN llm_daily_budget_tokens")
