"""core identity tables tenants sites users professionals patients

Task 2.1 (openspec/changes/kureha-mvp/tasks.md, Phase 2). Schema per
design.md §4.1. RLS (§4.2) is deliberately NOT enabled here -- it is applied
across every tenant table in a single sweep by task 2.9 (next work unit),
after tables 2.5-2.8 also exist.

`patients` identity is tenant-wide, not site-wide (design.md §4.1): the
same document_number must resolve to one patient record across every site of
a tenant, so uniqueness is `UNIQUE(tenant_id, document_number)`, not scoped
by `site_id`. `site_id` on `patients` is the (nullable) registration site,
informative only.

Raw SQL (`op.execute`) is used throughout instead of SQLAlchemy Core table
builders: this project has no declarative metadata (see migrations/env.py
-- SQLAlchemy Core, not the ORM, per design.md §1) and the CHECK/role
constraints below are most directly expressed as SQL.

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

    # NOTE (review fix on top of design.md's literal SQL, flagged not silently
    # applied -- see apply-progress): design.md §4.1 FKs `site_id`/`patient_id`/
    # `professional_id` as single-column references (or, for users.patient_id/
    # professional_id, no FK at all). That leaves tenant_id/site_id free to
    # disagree (a row could reference a site/patient/professional belonging to
    # a different tenant), which the RLS layer (task 2.9) would then silently
    # trust. `sites`/`patients`/`professionals` each get a `UNIQUE(tenant_id, id)`
    # so every FK from another table can be the composite `(tenant_id, x_id)`
    # form instead, tightening design.md's sketch rather than deviating from it.
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
