"""staff tables staff_members shifts

Task 2.6 (openspec/changes/kureha-mvp/tasks.md, Phase 2). Schema per
design.md §4.4/§6. `staff_members` is operational registry only (no HR
fields: no payroll/contracts/performance). `shifts` gets the same
anti-overlap `EXCLUDE USING gist` pattern already used for `availability`
(3505dc8ce3ad) and (implicitly) `appointments`, scoped per
`staff_member_id`.

RLS is deferred to task 2.9, same convention as every other Phase 2 schema
migration.

NOTE (tightening on top of design.md's literal SQL, flagged not silently
applied -- same class of fix as 8fc0dc6f958d/3505dc8ce3ad/5975cbe7665e/
7d88aa8f8a51): `site_id`/`user_id`/`professional_id` on `staff_members`, and
`site_id`/`staff_member_id` on `shifts`, are composite FKs
`(tenant_id, x_id) REFERENCES table(tenant_id, id)` instead of bare
`REFERENCES table(id)`, so a row belonging to a different tenant can never be
assigned. `staff_members` gets its own `UNIQUE(tenant_id, id)` so `shifts`
can FK into it the same way. `shifts` also gets its own `UNIQUE(tenant_id, id)`
(found in review: without it, `shifts` was the only tenant table with no
index whose leading column is `tenant_id`/`site_id`, forcing a sequential
scan across all tenants to evaluate task 2.9's RLS tenant/site filter --
its own `EXCLUDE USING gist` is keyed on `staff_member_id`/time-range, not
useful for that filter).

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
