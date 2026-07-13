"""session and rate limiting tables user_sessions rate_counters llm budget

Task 2.8 (openspec/changes/kureha-mvp/tasks.md, Phase 2). Schema per
design.md §4.4/§17.4/§19. `user_sessions` stores hashed refresh tokens
(never the token in the clear) with a rotation chain (`rotated_from`) used
to detect reuse of a rotated/revoked refresh (stolen-token signal, §17.4).
`rate_counters` backs the auth/token and LLM-daily-budget rate-limit
dimensions (§19); `tenant_id` is nullable because the pre-login IP-based
auth limit has no tenant yet.

RLS is deferred to task 2.9 for `user_sessions` (tenant-scoped). `rate_counters`
does NOT get RLS at all -- design.md §4.4 is explicit that it "vive fuera de
las policies de dato de paciente" (nullable tenant_id, touched only by the
rate-limiting middleware, never a domain use case); task 2.9's migration
documents this exclusion explicitly rather than silently omitting it.

NOTE (design.md gap, fixed here, flagged not silently applied): design.md's
literal SQL for `ix_rate_counters_expiry` is
`CREATE INDEX ... ON rate_counters (window_start) WHERE window_start < now() - interval '24 hours'`
-- Postgres rejects this outright ("functions in index predicate must be
marked IMMUTABLE"; confirmed against Postgres 16), since `now()` is STABLE,
not IMMUTABLE, and a partial index predicate must be immutable. design.md's
own prose right after that snippet already flags the ambiguity and offers
the fix: "alternativa equivalente: CREATE INDEX ix_rate_counters_window ON
rate_counters (window_start)" -- that plain (non-partial) index is what this
migration creates; the partial-predicate line from the snippet is not
executable and is not run.

NOTE (tightening on top of design.md's literal SQL, flagged not silently
applied -- same class of fix as every migration since 8fc0dc6f958d):
`user_sessions.user_id` is a composite FK `(tenant_id, user_id) REFERENCES
users(tenant_id, id)` instead of bare `REFERENCES users(id)`.
`user_sessions.rotated_from` is likewise tightened to a composite FK
`(tenant_id, rotated_from) REFERENCES user_sessions(tenant_id, id)` (own
`UNIQUE(tenant_id, id)` added) so a rotation chain can never cross tenants.

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
