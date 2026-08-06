from typing import Protocol


class SecretGeneratorPort(Protocol):
    def generate(self) -> str:
        """Returns a new cryptographically random, URL-safe opaque secret
        -- never persisted in the clear (only its hash is stored, see
        `SessionStorePort`)."""
        ...
