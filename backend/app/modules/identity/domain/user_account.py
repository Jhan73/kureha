from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class UserAccount:
    id: str
    tenant_id: str
    site_id: str
    role: str
    status: str
    email: str
    auth_subject: str | None
    email_verified_at: datetime | None

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    @property
    def is_linked_to_federated_provider(self) -> bool:
        return self.auth_subject is not None
