"""audit_logs site_id composite tenant fk

Revision ID: adacb9d7fd59
Revises: d5eb23089082
Create Date: 2026-07-13 22:42:21.312373

PR 4 review fix: `audit_logs.site_id` was left as a bare
`REFERENCES sites(id)` in migration 776b456050fe, unlike every sibling
table with a `site_id` column (`patients`, `professionals`, `availability`,
`appointments`, `consents`, `staff_members`/`shifts`), which all got the
composite `(tenant_id, site_id) REFERENCES sites (tenant_id, id)` treatment
during PR 2/PR 3's own review fixes -- a plain miss, not an intentional
exception. Without the composite FK, an `audit_logs` row's `site_id` is
only checked to exist somewhere in `sites`, not to belong to the row's own
`tenant_id`.
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
