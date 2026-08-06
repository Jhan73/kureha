from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EncryptedSecret:
    ciphertext: bytes
    nonce: bytes
    wrapped_dek: bytes
    key_version: int
