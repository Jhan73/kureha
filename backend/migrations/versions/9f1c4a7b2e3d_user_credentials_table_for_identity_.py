"""Add user_credentials for IdP subject and email authn resolution.

Separate from users (composite FK). UNIQUE per tenant on user_id, email,
and auth_subject (NULLs distinct). Tenant-only RLS; pre-auth lookup uses
elevated connection.

Revision ID: 9f1c4a7b2e3d
Revises: adacb9d7fd59
Create Date: 2026-07-14 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '9f1c4a7b2e3d'
down_revision: Union[str, Sequence[str], None] = 'adacb9d7fd59'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE TABLE user_credentials (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          user_id uuid NOT NULL,
          email text NOT NULL,
          auth_subject text,
          email_verified_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id, id),
          UNIQUE (tenant_id, user_id),
          UNIQUE (tenant_id, email),
          UNIQUE (tenant_id, auth_subject)
        )
        """
    )

    op.execute("ALTER TABLE user_credentials ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE user_credentials FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY user_credentials_tenant ON user_credentials FOR ALL
          USING (current_setting('app.tenant_id')::uuid = tenant_id)
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY user_credentials_tenant ON user_credentials")
    op.execute("ALTER TABLE user_credentials NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE user_credentials DISABLE ROW LEVEL SECURITY")
    op.execute("DROP TABLE user_credentials")
