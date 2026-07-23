"""`CredentialVaultPort` (design.md §7.4, tasks.md task 9.1): envelope
encryption/decryption for Google refresh tokens at rest. Implemented in MVP
by `AesGcmVault` (adapters/outbound/calendar/aes_gcm_vault.py).

Only `ConnectPatientCalendar` (encrypt, before persisting) and
`SyncAppointmentToCalendar` (decrypt, transiently in memory right before a
`CalendarSyncPort` call) ever touch this port -- no other use case decrypts
a refresh token. The plaintext this port hands back MUST NEVER be logged,
audited, or persisted anywhere outside this port's own encrypted storage."""

from typing import Protocol

from app.modules.calendar.domain.encrypted_secret import EncryptedSecret


class CredentialVaultPort(Protocol):
    async def encrypt(self, plaintext: bytes) -> EncryptedSecret:
        """Envelope-encrypts `plaintext` with a fresh, per-call DEK wrapped
        by the current KEK (design.md §7.4)."""
        ...

    async def decrypt(self, secret: EncryptedSecret) -> bytes:
        """Reverses `encrypt` -- unwraps the DEK with the KEK, then decrypts
        `secret.ciphertext`. Raises if the KEK/DEK/nonce/ciphertext do not
        match (tampered or corrupted row)."""
        ...
