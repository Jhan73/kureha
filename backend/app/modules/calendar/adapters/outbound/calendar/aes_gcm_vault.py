"""`AesGcmVault`: `CredentialVaultPort` impl using envelope AES-256-GCM
(design.md §7.4, ADR-12) with the KEK fetched from AWS Secrets Manager
(design.md §22.5/§22.6, ADR-24). Mirrors §22.6's literal `boto3.client(...,
endpoint_url=settings.aws_endpoint_url or None)` pattern exactly -- reads
`app.config.settings` directly in `__init__` rather than taking
`endpoint_url` as a constructor argument, the established convention for
boto3-based adapters specifically (distinct from `SupabaseAuthAdapter`'s
constructor-injected `base_url`, which is a non-AWS external HTTP
integration). `settings.aws_endpoint_url` is `None` in production, so
boto3 talks to real AWS via the ECS task's IAM role with zero code changes
(§22.8's migration checklist).

**Envelope scheme:** per credential, a fresh random 256-bit DEK encrypts
`plaintext` under AES-256-GCM with a fresh random 96-bit nonce; the SAME
nonce also wraps the DEK itself under the KEK (AES-256-GCM). Reusing one
nonce for two DIFFERENT keys (DEK vs KEK) is cryptographically safe --
AES-GCM's nonce-uniqueness requirement is per-KEY, not global -- and lets
`calendar_credentials` store a single `nonce` column (migration
00d985a7bfa5) instead of two. `ciphertext`/`nonce`/`wrapped_dek`/
`key_version` are the only things ever persisted; the plaintext token and
the unwrapped DEK never leave this class's stack frame.

**KEK caching:** fetched once per `AesGcmVault` instance and cached for its
lifetime (not cross-request in the RBAC/ADR-16 sense -- this is a
data-encryption key with no revocation-security implication, unlike a
permission grant; reducing Secrets Manager calls is a pure performance win
here). `boto3`'s `get_secret_value` is a blocking call -- wrapped in
`asyncio.to_thread` so it never blocks the event loop, no precedent for
this existed yet in the codebase (SupabaseAuthAdapter/GoogleCalendarAdapter
use `httpx.AsyncClient`, which is natively async; boto3 has none).

**Key rotation (out of scope, flagged not silently assumed):** `key_version`
is stored for a future rotation mechanism (design.md §7.4: "la rotacion de
KEK ... solo re-envuelve DEKs"), but no rotation job/endpoint exists in this
MVP -- `decrypt` always uses the CURRENT KEK regardless of
`secret.key_version`, which is only correct as long as exactly one KEK
version has ever existed."""

import asyncio
import base64
import json
import os

import boto3
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings
from app.modules.calendar.domain.encrypted_secret import EncryptedSecret

_DEFAULT_SECRET_ID = "kureha/dev/kek"


class AesGcmVault:
    def __init__(self, *, secret_id: str = _DEFAULT_SECRET_ID) -> None:
        self._secret_id = secret_id
        self._client = boto3.client(
            "secretsmanager",
            region_name=settings.aws_default_region,
            endpoint_url=settings.aws_endpoint_url or None,
        )
        self._kek_cache: tuple[bytes, int] | None = None

    async def encrypt(self, plaintext: bytes) -> EncryptedSecret:
        kek, key_version = await self._get_kek()
        dek = AESGCM.generate_key(bit_length=256)
        nonce = os.urandom(12)
        ciphertext = AESGCM(dek).encrypt(nonce, plaintext, None)
        wrapped_dek = AESGCM(kek).encrypt(nonce, dek, None)
        return EncryptedSecret(ciphertext=ciphertext, nonce=nonce, wrapped_dek=wrapped_dek, key_version=key_version)

    async def decrypt(self, secret: EncryptedSecret) -> bytes:
        kek, _key_version = await self._get_kek()
        dek = AESGCM(kek).decrypt(secret.nonce, secret.wrapped_dek, None)
        return AESGCM(dek).decrypt(secret.nonce, secret.ciphertext, None)

    async def _get_kek(self) -> tuple[bytes, int]:
        if self._kek_cache is None:
            response = await asyncio.to_thread(self._client.get_secret_value, SecretId=self._secret_id)
            payload = json.loads(response["SecretString"])
            kek = base64.b64decode(payload["kek_base64"])
            key_version = int(payload["version"])
            self._kek_cache = (kek, key_version)
        return self._kek_cache
