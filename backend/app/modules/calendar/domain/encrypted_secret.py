"""`EncryptedSecret`: the envelope-encrypted shape of one secret at rest
(design.md §7.4). Produced/consumed by `CredentialVaultPort` and mapped
1:1 onto `calendar_credentials`' `encrypted_refresh_token`/`nonce`/
`wrapped_dek`/`key_version` columns (migration 00d985a7bfa5) -- pure data,
no crypto logic lives here (that is `AesGcmVault`'s job, adapters/outbound/
calendar/aes_gcm_vault.py)."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EncryptedSecret:
    ciphertext: bytes
    nonce: bytes
    wrapped_dek: bytes
    key_version: int
