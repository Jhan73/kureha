"""Schedule rate_counters cleanup via pg_cron when the extension exists.

Guarded on pg_available_extensions: vanilla postgres images lack pg_cron
(needs shared_preload_libraries), so local upgrade is a no-op; RDS can
register the hourly DELETE of rows older than 24h.

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
