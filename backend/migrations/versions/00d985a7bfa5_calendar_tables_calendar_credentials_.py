"""Add calendar_credentials and calendar_sync tables.

Tenant-wide credentials per patient; UNIQUE(tenant_id, idempotency_key) for
sync retries. Adds UNIQUE(tenant_id, id) on appointments for composite FK.
Token columns are opaque bytea (encryption is application-layer).

Revision ID: 00d985a7bfa5
Revises: d0e2489a94b8
Create Date: 2026-07-13 11:37:30.368666

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '00d985a7bfa5'
down_revision: Union[str, Sequence[str], None] = 'd0e2489a94b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "ALTER TABLE appointments ADD CONSTRAINT appointments_tenant_id_id_key UNIQUE (tenant_id, id)"
    )

    op.execute(
        """
        CREATE TABLE calendar_credentials (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          patient_id uuid NOT NULL,
          encrypted_refresh_token bytea NOT NULL,
          nonce bytea NOT NULL,
          wrapped_dek bytea NOT NULL,
          key_version int NOT NULL,
          scope text NOT NULL DEFAULT 'https://www.googleapis.com/auth/calendar.events',
          connected_at timestamptz NOT NULL DEFAULT now(),
          revoked_at timestamptz,
          FOREIGN KEY (tenant_id, patient_id) REFERENCES patients (tenant_id, id),
          UNIQUE (tenant_id, patient_id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE calendar_sync (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          site_id uuid NOT NULL,
          appointment_id uuid NOT NULL,
          idempotency_key text NOT NULL,
          google_event_id text,
          sync_status text NOT NULL DEFAULT 'pending'
            CHECK (sync_status IN ('pending','ok','failed')),
          attempts int NOT NULL DEFAULT 0,
          last_error text,
          updated_at timestamptz NOT NULL DEFAULT now(),
          FOREIGN KEY (tenant_id, site_id) REFERENCES sites (tenant_id, id),
          FOREIGN KEY (tenant_id, appointment_id) REFERENCES appointments (tenant_id, id),
          UNIQUE (appointment_id),
          UNIQUE (tenant_id, idempotency_key)
        )
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE calendar_sync")
    op.execute("DROP TABLE calendar_credentials")
    op.execute("ALTER TABLE appointments DROP CONSTRAINT appointments_tenant_id_id_key")
