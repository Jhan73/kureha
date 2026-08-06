"""Add action_permissions, role_permissions, and user_permissions.

action_permissions is a global catalog (no RLS). Adds UNIQUE(tenant_id, id)
on users for composite FK from user_permissions.

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
