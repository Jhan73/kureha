from typing import Protocol

from app.modules.calendar.domain.encrypted_secret import EncryptedSecret


class CredentialVaultPort(Protocol):
    async def encrypt(self, plaintext: bytes) -> EncryptedSecret:
        """Envelope-encrypt with a fresh DEK wrapped by the current KEK."""
        ...

    async def decrypt(self, secret: EncryptedSecret) -> bytes:
        """Unwrap DEK and decrypt; raises if tampered/corrupted."""
        ...
