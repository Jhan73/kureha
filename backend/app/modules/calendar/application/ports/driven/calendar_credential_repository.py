from typing import Protocol

from app.modules.calendar.domain.calendar_credential import EncryptedCredentialRecord
from app.modules.calendar.domain.encrypted_secret import EncryptedSecret


class CalendarCredentialRepositoryPort(Protocol):
    async def get(self, tenant_id: str, patient_id: str) -> EncryptedCredentialRecord | None:
        """Credential row (revoked or not); None if never connected."""
        ...

    async def save(
        self, tenant_id: str, patient_id: str, secret: EncryptedSecret, *, scope: str
    ) -> EncryptedCredentialRecord:
        """Upsert encrypted token; reconnect replaces previous."""
        ...

    async def revoke(self, tenant_id: str, patient_id: str) -> None:
        """Sets revoked_at and clears encrypted token."""
        ...
