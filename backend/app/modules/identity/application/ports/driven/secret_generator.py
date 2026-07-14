"""`SecretGeneratorPort`: mints the opaque refresh-token plaintext
(design.md §17.4 -- "refresh opaco en `user_sessions`"). Kept local to
`modules/identity` rather than `shared_kernel` (unlike `ClockPort`/
`IdGeneratorPort`) since it is not a generic cross-module value type --
only the identity module needs cryptographically random opaque secrets;
`shared_kernel`'s contents are a closed, explicitly enumerated list
(backend/AGENTS.md §2.5, design.md §2.5) that this does not belong in."""

from typing import Protocol


class SecretGeneratorPort(Protocol):
    def generate(self) -> str:
        """Returns a new cryptographically random, URL-safe opaque secret
        -- never persisted in the clear (only its hash is stored, see
        `SessionStorePort`)."""
        ...
