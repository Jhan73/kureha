"""Seed the system tenant row (`SYSTEM_TENANT_ID`) used as the `tenant_id`
fallback when auditing denies that have no real tenant to attribute to
(unmapped identity, missing claims -- see `AccessControlMiddleware`).

Without this row, `audit_logs`'s FK to `tenants(id)` rejects those writes;
since they go through `record_audit_best_effort`, the failure is silently
swallowed and the events are never audited.

`status='suspended'` so `TenantPolicy.is_usable` is always false for this
row -- it must never be usable as a normal, operable tenant.

Revision ID: a1c7e9d34f02
Revises: 9f1c4a7b2e3d
Create Date: 2026-08-06 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1c7e9d34f02'
down_revision: Union[str, Sequence[str], None] = '9f1c4a7b2e3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SYSTEM_TENANT_ID = '00000000-0000-0000-0000-000000000000'


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        f"""
        INSERT INTO tenants (id, name, status)
        VALUES ('{_SYSTEM_TENANT_ID}', 'Kureha System', 'suspended')
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(f"DELETE FROM tenants WHERE id = '{_SYSTEM_TENANT_ID}'")
