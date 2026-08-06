from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ConsentPolicyVersion:
    """Published consent text version; at most one is_current per tenant."""

    tenant_id: str
    version: str
    document_hash: str
    is_current: bool
    published_at: datetime


@dataclass(frozen=True, slots=True)
class Consent:
    """Patient acceptance/revocation of a policy version; status is accepted|revoked."""

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
