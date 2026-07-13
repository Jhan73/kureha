"""rbac tables action_permissions role_permissions user_permissions

Task 2.5 (openspec/changes/kureha-mvp/tasks.md, Phase 2). Schema per
design.md §4.4/§5. `action_permissions` is a global catalog (seeded in code,
not tenant-scoped, no RLS -- §4.4: "catalogo global ... sin RLS").
`role_permissions`/`user_permissions` are tenant-scoped grants, resolved with
more-specific-wins precedence (user override > role grant > deny-by-default,
§5.2) by the application layer -- this migration only enforces the shape
(uniqueness, FK to the action catalog), not the precedence logic itself.

RLS is deferred to task 2.9, same convention as every other Phase 2 schema
migration (8fc0dc6f958d onward).

NOTE (tightening on top of design.md's literal SQL, flagged not silently
applied -- same class of fix as apply-progress's notes on 8fc0dc6f958d):
`users` never got a `UNIQUE(tenant_id, id)` in 8fc0dc6f958d (nothing FK'd
into it yet at that point). `user_permissions.user_id` is the first FK into
`users`, so this migration adds that unique constraint here and uses the
composite FK `(tenant_id, user_id) REFERENCES users(tenant_id, id)` --
otherwise a permission override could target a `user_id` belonging to a
different tenant, the same class of bug the composite FKs elsewhere already
close.

Revision ID: 7d88aa8f8a51
Revises: 776b456050fe
Create Date: 2026-07-13 11:32:05.564288

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7d88aa8f8a51'
down_revision: Union[str, Sequence[str], None] = '776b456050fe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE TABLE action_permissions (
          key text PRIMARY KEY,
          description text NOT NULL,
          requires_hitl boolean NOT NULL DEFAULT false,
          bulk_cancel_threshold int NOT NULL DEFAULT 3
        )
        """
    )

    op.execute(
        """
        CREATE TABLE role_permissions (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          role text NOT NULL CHECK (role IN ('patient','reception','professional','admin')),
          action text NOT NULL REFERENCES action_permissions(key),
          allowed boolean NOT NULL DEFAULT true,
          PRIMARY KEY (tenant_id, role, action)
        )
        """
    )

    op.execute("ALTER TABLE users ADD CONSTRAINT users_tenant_id_id_key UNIQUE (tenant_id, id)")

    op.execute(
        """
        CREATE TABLE user_permissions (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          user_id uuid NOT NULL,
          action text NOT NULL REFERENCES action_permissions(key),
          allowed boolean NOT NULL,
          PRIMARY KEY (tenant_id, user_id, action),
          FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id, id)
        )
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE user_permissions")
    op.execute("ALTER TABLE users DROP CONSTRAINT users_tenant_id_id_key")
    op.execute("DROP TABLE role_permissions")
    op.execute("DROP TABLE action_permissions")
