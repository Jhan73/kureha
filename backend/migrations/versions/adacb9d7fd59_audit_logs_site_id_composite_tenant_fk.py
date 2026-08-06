"""Tighten audit_logs.site_id to composite (tenant_id, site_id) FK.

Revision ID: adacb9d7fd59
Revises: d5eb23089082
Create Date: 2026-07-13 22:42:21.312373

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'adacb9d7fd59'
down_revision: Union[str, Sequence[str], None] = 'd5eb23089082'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE audit_logs DROP CONSTRAINT audit_logs_site_id_fkey")
    op.execute(
        "ALTER TABLE audit_logs ADD CONSTRAINT audit_logs_site_id_fkey "
        "FOREIGN KEY (tenant_id, site_id) REFERENCES sites (tenant_id, id)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE audit_logs DROP CONSTRAINT audit_logs_site_id_fkey")
    op.execute(
        "ALTER TABLE audit_logs ADD CONSTRAINT audit_logs_site_id_fkey "
        "FOREIGN KEY (site_id) REFERENCES sites (id)"
    )
