"""Task 9.2: `AesGcmVault` -- envelope AES-256-GCM encryption with the KEK
fetched from Secrets Manager (design.md §7.4/§22.6, ADR-24). Real network
call against LocalStack -- no mocking of boto3/cryptography, same
"prefer real infra over doubles" spirit as `rls_conn`'s tests against real
Postgres. Requires LocalStack running with the `kureha/dev/kek` secret
already provisioned (infra/localstack/init/01_secrets.sh) and
`AWS_ENDPOINT_URL` pointed at it."""

import dataclasses

import pytest

from app.config import settings
from app.modules.calendar.adapters.outbound.calendar.aes_gcm_vault import AesGcmVault

pytestmark = pytest.mark.skipif(
    not settings.aws_endpoint_url, reason="requires AWS_ENDPOINT_URL pointed at a running LocalStack"
)


async def test_encrypt_then_decrypt_round_trips_the_plaintext() -> None:
    vault = AesGcmVault()

    secret = await vault.encrypt(b"super-secret-refresh-token")
    decrypted = await vault.decrypt(secret)

    assert decrypted == b"super-secret-refresh-token"


async def test_ciphertext_never_contains_the_plaintext() -> None:
    vault = AesGcmVault()

    secret = await vault.encrypt(b"super-secret-refresh-token")

    assert secret.ciphertext != b"super-secret-refresh-token"
    assert b"super-secret-refresh-token" not in secret.ciphertext


async def test_two_encryptions_of_the_same_plaintext_use_different_nonces_and_ciphertexts() -> None:
    vault = AesGcmVault()

    first = await vault.encrypt(b"same-plaintext")
    second = await vault.encrypt(b"same-plaintext")

    assert first.nonce != second.nonce
    assert first.ciphertext != second.ciphertext


async def test_key_version_matches_the_kek_secrets_manager_version() -> None:
    vault = AesGcmVault()

    secret = await vault.encrypt(b"x")

    assert secret.key_version == 1


async def test_tampered_ciphertext_fails_to_decrypt() -> None:
    vault = AesGcmVault()
    secret = await vault.encrypt(b"super-secret-refresh-token")
    tampered = dataclasses.replace(secret, ciphertext=b"\x00" * len(secret.ciphertext))

    with pytest.raises(Exception):  # noqa: B017 -- cryptography raises its own InvalidTag
        await vault.decrypt(tampered)
