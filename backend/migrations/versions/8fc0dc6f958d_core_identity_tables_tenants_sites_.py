"""Add tenants, sites, professionals, patients, and users tables.

patients are tenant-wide (UNIQUE on tenant_id+document_number); site_id is
nullable registration site only. Composite FKs use UNIQUE(tenant_id, id).

Revision ID: 8fc0dc6f958d
Revises:
Create Date: 2026-07-13 10:14:22.549545

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '8fc0dc6f958d'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE TABLE tenants (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          name text NOT NULL,
          status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended')),
          created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    # UNIQUE(tenant_id, id) enables composite FKs for tenant+site integrity.
    op.execute(
        """
        CREATE TABLE sites (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          name text NOT NULL,
          UNIQUE (tenant_id, id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE professionals (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          site_id uuid NOT NULL,
          name text NOT NULL,
          specialty text,
          FOREIGN KEY (tenant_id, site_id) REFERENCES sites (tenant_id, id),
          UNIQUE (tenant_id, id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE patients (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          site_id uuid,
          name text NOT NULL,
          document_number text NOT NULL,
          email text,
          phone text,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE (tenant_id, document_number),
          UNIQUE (tenant_id, id),
          FOREIGN KEY (tenant_id, site_id) REFERENCES sites (tenant_id, id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE users (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          site_id uuid NOT NULL,
          role text NOT NULL CHECK (role IN ('patient','reception','professional','admin')),
          status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive')),
          patient_id uuid,
          professional_id uuid,
          CHECK (role <> 'patient'      OR patient_id      IS NOT NULL),
          CHECK (role <> 'professional' OR professional_id IS NOT NULL),
          FOREIGN KEY (tenant_id, site_id) REFERENCES sites (tenant_id, id),
          FOREIGN KEY (tenant_id, patient_id) REFERENCES patients (tenant_id, id),
          FOREIGN KEY (tenant_id, professional_id) REFERENCES professionals (tenant_id, id)
        )
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE users")
    op.execute("DROP TABLE patients")
    op.execute("DROP TABLE professionals")
    op.execute("DROP TABLE sites")
    op.execute("DROP TABLE tenants")
