"""calendar tables calendar_credentials calendar_sync

Task 2.7 (openspec/changes/kureha-mvp/tasks.md, Phase 2). Schema per
design.md §4.4/§7. `calendar_credentials` is tenant-wide identity, same
rationale as `patients` (8fc0dc6f958d): one Google connection per patient
regardless of site. `calendar_sync.idempotency_key` (ADR-18, §7.6) is the
deterministic id derived from `appointment_id` that makes `events.insert`
retries safe -- `UNIQUE(tenant_id, idempotency_key)` is what actually
guarantees exactly one `google_event_id` per appointment.

RLS is deferred to task 2.9, same convention as every other Phase 2 schema
migration. Encryption itself (AES-256-GCM envelope, KEK in Secrets Manager)
is application-layer (`CredentialVaultPort`/`AesGcmVault`, Phase 9) -- out of
scope for this schema-only migration; `encrypted_refresh_token`/`nonce`/
`wrapped_dek` are opaque `bytea` here.

NOTE (tightening on top of design.md's literal SQL, flagged not silently
applied -- same class of fix as every migration since 8fc0dc6f958d):
`calendar_credentials.patient_id` and `calendar_sync.site_id`/
`appointment_id` are composite FKs `(tenant_id, x_id) REFERENCES
table(tenant_id, id)` instead of bare `REFERENCES table(id)`. `appointments`
never got a `UNIQUE(tenant_id, id)` in 3505dc8ce3ad (nothing FK'd into it
yet); `calendar_sync.appointment_id` is the first FK into `appointments`, so
this migration adds that unique constraint here (same situation as
`users`/7d88aa8f8a51).

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
