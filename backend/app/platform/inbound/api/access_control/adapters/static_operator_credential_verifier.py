import hashlib
import hmac

from app.platform.inbound.api.access_control.operator_identity import (
    OperatorCredentialError,
    OperatorIdentity,
)


class StaticOperatorCredentialVerifier:
    """Verifies `X-Kureha-Ops-Key: <key_id>.<secret>` against `settings.ops_bootstrap_credentials`
    (`key_id:sha256_hex` pairs, comma-separated). Fail closed: empty config denies everything."""

    def __init__(self, credentials_config: str) -> None:
        self._digests = self._parse(credentials_config)

    def verify(self, header_value: str | None) -> OperatorIdentity:
        if not self._digests:
            raise OperatorCredentialError("ops_bootstrap_credentials is empty")
        if not header_value:
            raise OperatorCredentialError("missing X-Kureha-Ops-Key header")

        key_id, separator, secret = header_value.partition(".")
        if not separator or not key_id or not secret:
            raise OperatorCredentialError("malformed X-Kureha-Ops-Key header")

        expected_digest = self._digests.get(key_id)
        if expected_digest is None:
            raise OperatorCredentialError("unknown key_id")

        actual_digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(actual_digest, expected_digest):
            raise OperatorCredentialError("secret does not match")

        return OperatorIdentity(key_id=key_id)

    @staticmethod
    def _parse(credentials_config: str) -> dict[str, str]:
        digests: dict[str, str] = {}
        for entry in credentials_config.split(","):
            entry = entry.strip()
            if not entry:
                continue
            key_id, _, digest = entry.partition(":")
            if key_id and digest:
                digests[key_id] = digest
        return digests
