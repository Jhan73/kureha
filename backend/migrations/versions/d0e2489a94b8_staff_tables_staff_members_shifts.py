"""Add staff_members and shifts tables with overlap exclusion.

Composite FKs for tenant integrity; UNIQUE(tenant_id, id) on both for
RLS/index friendliness and shifts FK into staff_members.

Revision ID: d0e2489a94b8
Revises: 7d88aa8f8a51
Create Date: 2026-07-13 11:34:51.483368

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd0e2489a94b8'
down_revision: Union[str, Sequence[str], None] = '7d88aa8f8a51'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE TABLE staff_members (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          site_id uuid NOT NULL,
          user_id uuid,
          professional_id uuid,
          name text NOT NULL,
          operational_role text NOT NULL CHECK (operational_role IN ('reception','professional','admin')),
          status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive')),
          activated_at timestamptz NOT NULL DEFAULT now(),
          deactivated_at timestamptz,
          FOREIGN KEY (tenant_id, site_id) REFERENCES sites (tenant_id, id),
          FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id, id),
          FOREIGN KEY (tenant_id, professional_id) REFERENCES professionals (tenant_id, id),
          UNIQUE (tenant_id, id),
          UNIQUE (site_id, professional_id),
          UNIQUE (site_id, user_id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE shifts (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          site_id uuid NOT NULL,
          staff_member_id uuid NOT NULL,
          starts_at timestamptz NOT NULL,
          ends_at timestamptz NOT NULL,
          CHECK (ends_at > starts_at),
          FOREIGN KEY (tenant_id, site_id) REFERENCES sites (tenant_id, id),
          FOREIGN KEY (tenant_id, staff_member_id) REFERENCES staff_members (tenant_id, id),
          UNIQUE (tenant_id, id),
          EXCLUDE USING gist (
            staff_member_id WITH =,
            tstzrange(starts_at, ends_at) WITH &&
          )
        )
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE shifts")
    op.execute("DROP TABLE staff_members")
