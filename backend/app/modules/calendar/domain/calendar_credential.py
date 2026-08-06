from dataclasses import dataclass
from datetime import datetime

from app.modules.calendar.domain.encrypted_secret import EncryptedSecret


@dataclass(frozen=True, slots=True)
class CalendarCredential:
    patient_id: str
    refresh_token: str
    scope: str


@dataclass(frozen=True, slots=True)
class EncryptedCredentialRecord:
    id: str
    tenant_id: str
    patient_id: str
    secret: EncryptedSecret
    scope: str
    connected_at: datetime
    revoked_at: datetime | None

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None
