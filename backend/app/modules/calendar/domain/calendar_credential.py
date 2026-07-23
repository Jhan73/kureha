"""`CalendarCredential`: the DECRYPTED, in-memory-only shape of a patient's
Google Calendar connection (design.md §7.3/§7.4). Only ever constructed
transiently, right before a `CalendarSyncPort` call, from an `EncryptedSecret`
row passed through `CredentialVaultPort.decrypt` -- the plaintext refresh
token this carries MUST NEVER be logged, audited, or persisted anywhere
outside `CredentialVaultPort`'s own encrypted storage (design.md §7.4: "el
plaintext del token nunca toca ... los logs ni la auditoria").

`EncryptedCredentialRecord` is the encrypted-at-rest counterpart returned by
`CalendarCredentialRepositoryPort` -- extends `EncryptedSecret` with the
row's own identity/scope/revocation metadata, none of which is secret."""

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
