"""Domain entities mirroring `consent_policies`/`consents` (design.md §4.1,
§11). Pure value objects -- no IO, no policy/business-rule logic (that lives
in `consent_policy.py`)."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ConsentPolicyVersion:
    """One row of the `consent_policies` catalog: a published version of the
    tenant's consent text. At most one row per tenant has `is_current=True`
    (enforced by `one_current_policy_per_tenant`, migration
    `5975cbe7665e`)."""

    tenant_id: str
    version: str
    document_hash: str
    is_current: bool
    published_at: datetime


@dataclass(frozen=True, slots=True)
class Consent:
    """One row of `consents`: a patient's acceptance (or revocation) of a
    specific `ConsentPolicyVersion`. `status` mirrors the DB CHECK
    constraint (`accepted`|`revoked`) -- kept as the literal string rather
    than an enum here since it round-trips directly to/from the
    `consents.status` column with no translation needed."""

    id: str
    tenant_id: str
    site_id: str | None
    patient_id: str
    policy_version: str
    status: str
    document_hash: str
    channel: str
    actor_id: str | None
    accepted_at: datetime | None
    revoked_at: datetime | None
