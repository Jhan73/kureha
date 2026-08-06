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
