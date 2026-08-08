from dataclasses import dataclass
from typing import Protocol

from app.shared_kernel.errors import NotAuthorizedError


@dataclass(frozen=True, slots=True)
class OperatorIdentity:
    key_id: str


class OperatorCredentialError(NotAuthorizedError):
    """`X-Kureha-Ops-Key` is missing, malformed, or does not verify against config."""


class OperatorCredentialVerifierPort(Protocol):
    def verify(self, header_value: str | None) -> OperatorIdentity:
        """OperatorIdentity if `header_value` verifies; raises OperatorCredentialError otherwise."""
        ...
