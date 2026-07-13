"""scheduling tables availability appointments

Task 2.2 (openspec/changes/kureha-mvp/tasks.md, Phase 2). Schema per
design.md §4.1. Anti double-booking is enforced by Postgres itself via
`EXCLUDE USING gist`, backed by the `btree_gist` extension already created
in `infra/postgres/init/01_extensions.sql` (extensions require superuser
privileges the migration-time app_user role may not have on RDS -- see that
file's own comment -- so they are never `CREATE EXTENSION`'d from a
migration).

RLS is deferred to task 2.9, same as migration 8fc0dc6f958d.

NOTE (review fix on top of design.md's literal SQL, flagged not silently
applied -- see apply-progress): `site_id` on both tables is now a composite
FK `(tenant_id, site_id) REFERENCES sites(tenant_id, id)` instead of a bare
`REFERENCES sites(id)`, so a site belonging to a different tenant can no
longer be assigned (same tightening as `8fc0dc6f958d`'s `professionals`/
`patients`/`users`). `appointments` also gets `CHECK (ends_at > starts_at)`,
matching `availability`'s existing check -- design.md's sketch omitted it,
letting a zero-length appointment silently bypass the `EXCLUDE` constraint
(an empty `tstzrange` never overlaps anything).

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
