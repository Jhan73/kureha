"""Add consent_policies and consents tables.

Tenant-scoped (one current policy per tenant via partial unique index).
Composite FK for tenant+site; CHECK ties status to accepted_at/revoked_at.

Revision ID: 5975cbe7665e
Revises: 3505dc8ce3ad
Create Date: 2026-07-13 10:14:26.192033

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '5975cbe7665e'
down_revision: Union[str, Sequence[str], None] = '3505dc8ce3ad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE TABLE consent_policies (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          version text NOT NULL,
          document_hash text NOT NULL,
          is_current boolean NOT NULL DEFAULT false,
          published_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, version)
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX one_current_policy_per_tenant
          ON consent_policies (tenant_id) WHERE is_current
        """
    )

    op.execute(
        """
        CREATE TABLE consents (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          site_id uuid,
          patient_id uuid NOT NULL REFERENCES patients(id),
          policy_version text NOT NULL,
          status text NOT NULL CHECK (status IN ('accepted','revoked')),
          document_hash text NOT NULL,
          channel text NOT NULL,
          actor_id uuid,
          accepted_at timestamptz,
          revoked_at timestamptz,
          FOREIGN KEY (tenant_id, policy_version) REFERENCES consent_policies (tenant_id, version),
          FOREIGN KEY (tenant_id, site_id) REFERENCES sites (tenant_id, id),
          CHECK (
            (status = 'accepted' AND accepted_at IS NOT NULL AND revoked_at IS NULL)
            OR
            (status = 'revoked' AND accepted_at IS NOT NULL AND revoked_at IS NOT NULL)
          )
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_consents_lookup ON consents (tenant_id, patient_id, status, policy_version)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX ix_consents_lookup")
    op.execute("DROP TABLE consents")
    op.execute("DROP INDEX one_current_policy_per_tenant")
    op.execute("DROP TABLE consent_policies")
