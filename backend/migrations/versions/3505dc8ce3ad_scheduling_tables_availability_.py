"""Add availability and appointments with gist overlap exclusion.

Requires btree_gist (infra/postgres/init). Composite FK for tenant+site
integrity; appointments CHECK (ends_at > starts_at) so empty ranges cannot
bypass EXCLUDE.

Revision ID: 3505dc8ce3ad
Revises: 8fc0dc6f958d
Create Date: 2026-07-13 10:14:24.438145

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '3505dc8ce3ad'
down_revision: Union[str, Sequence[str], None] = '8fc0dc6f958d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE TABLE availability (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          site_id uuid NOT NULL,
          professional_id uuid NOT NULL REFERENCES professionals(id),
          starts_at timestamptz NOT NULL,
          ends_at timestamptz NOT NULL,
          status text NOT NULL DEFAULT 'available' CHECK (status IN ('available','reserved','blocked')),
          CHECK (ends_at > starts_at),
          FOREIGN KEY (tenant_id, site_id) REFERENCES sites (tenant_id, id),
          EXCLUDE USING gist (
            professional_id WITH =,
            tstzrange(starts_at, ends_at) WITH &&
          )
        )
        """
    )

    op.execute(
        """
        CREATE TABLE appointments (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          site_id uuid NOT NULL,
          patient_id uuid NOT NULL REFERENCES patients(id),
          professional_id uuid NOT NULL REFERENCES professionals(id),
          availability_id uuid NOT NULL REFERENCES availability(id),
          starts_at timestamptz NOT NULL,
          ends_at timestamptz NOT NULL,
          status text NOT NULL DEFAULT 'scheduled'
            CHECK (status IN ('scheduled','rescheduled','cancelled','completed','no_show')),
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CHECK (ends_at > starts_at),
          FOREIGN KEY (tenant_id, site_id) REFERENCES sites (tenant_id, id),
          EXCLUDE USING gist (
            professional_id WITH =,
            tstzrange(starts_at, ends_at) WITH &&
          ) WHERE (status IN ('scheduled','rescheduled'))
        )
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE appointments")
    op.execute("DROP TABLE availability")
