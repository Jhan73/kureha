import hashlib

import pytest

from app.platform.inbound.api.access_control.adapters.static_operator_credential_verifier import (
    StaticOperatorCredentialVerifier,
)
from app.platform.inbound.api.access_control.operator_identity import OperatorCredentialError, OperatorIdentity


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def test_valid_key_returns_operator_identity() -> None:
    verifier = StaticOperatorCredentialVerifier(f"op1:{_digest('s3cr3t')}")

    identity = verifier.verify("op1.s3cr3t")

    assert identity == OperatorIdentity(key_id="op1")


def test_multiple_configured_operators_each_verify_independently() -> None:
    verifier = StaticOperatorCredentialVerifier(f"op1:{_digest('secret-one')},op2:{_digest('secret-two')}")

    assert verifier.verify("op1.secret-one") == OperatorIdentity(key_id="op1")
    assert verifier.verify("op2.secret-two") == OperatorIdentity(key_id="op2")


def test_wrong_secret_is_denied() -> None:
    verifier = StaticOperatorCredentialVerifier(f"op1:{_digest('s3cr3t')}")

    with pytest.raises(OperatorCredentialError):
        verifier.verify("op1.wrong-secret")


def test_unknown_key_id_is_denied() -> None:
    verifier = StaticOperatorCredentialVerifier(f"op1:{_digest('s3cr3t')}")

    with pytest.raises(OperatorCredentialError):
        verifier.verify("op2.s3cr3t")


def test_empty_config_denies_even_a_well_formed_header() -> None:
    verifier = StaticOperatorCredentialVerifier("")

    with pytest.raises(OperatorCredentialError):
        verifier.verify("op1.s3cr3t")


def test_missing_header_is_denied() -> None:
    verifier = StaticOperatorCredentialVerifier(f"op1:{_digest('s3cr3t')}")

    with pytest.raises(OperatorCredentialError):
        verifier.verify(None)


def test_malformed_header_without_separator_is_denied() -> None:
    verifier = StaticOperatorCredentialVerifier(f"op1:{_digest('s3cr3t')}")

    with pytest.raises(OperatorCredentialError):
        verifier.verify("op1-s3cr3t-no-dot")


def test_malformed_header_with_empty_secret_is_denied() -> None:
    verifier = StaticOperatorCredentialVerifier(f"op1:{_digest('s3cr3t')}")

    with pytest.raises(OperatorCredentialError):
        verifier.verify("op1.")


def test_malformed_header_with_empty_key_id_is_denied() -> None:
    verifier = StaticOperatorCredentialVerifier(f"op1:{_digest('s3cr3t')}")

    with pytest.raises(OperatorCredentialError):
        verifier.verify(".s3cr3t")
