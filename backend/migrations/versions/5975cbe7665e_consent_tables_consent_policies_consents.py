"""consent tables consent_policies consents

Task 2.3 (openspec/changes/kureha-mvp/tasks.md, Phase 2). Schema per
design.md §4.1 and §11. Both tables are tenant-scoped, not site-scoped: a
clinic (tenant) is its own legal entity and owns exactly one current consent
policy version at a time, regardless of which site captured it -- enforced
by the partial unique index below, not by application code.

RLS is deferred to task 2.9, same as migrations 8fc0dc6f958d/3505dc8ce3ad.
The consent-policy legal text itself (v1) remains a pending business input
(design.md §11/§16) -- out of scope for this schema-only migration.

NOTE (review fixes on top of design.md's literal SQL, flagged not silently
applied -- see apply-progress):
1. `consents.site_id` is now a composite FK `(tenant_id, site_id) REFERENCES
   sites(tenant_id, id)` instead of a bare `REFERENCES sites(id)`, same
   tightening as `8fc0dc6f958d`/`3505dc8ce3ad`.
2. `consents` gets a CHECK tying `status` to `accepted_at`/`revoked_at`:
   `accepted` requires `accepted_at` set and `revoked_at` unset; `revoked`
   requires both set (a consent must have been accepted before it can be
   revoked). design.md's sketch left both columns plainly nullable with no
   cross-column constraint -- a legal-evidence record (Ley 29733) should not
   be representable with a status its own timestamps contradict.

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
