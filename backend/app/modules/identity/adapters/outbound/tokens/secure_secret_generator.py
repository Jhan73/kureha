"""`SecureSecretGenerator`: the only production `SecretGeneratorPort` impl
-- trivial enough (stdlib `secrets`, no IO) that, per the same convention as
`shared_kernel`'s `SystemClock`/`UuidGenerator`, it does not warrant more
than this one function-sized class."""

import secrets


class SecureSecretGenerator:
    def generate(self) -> str:
        return secrets.token_urlsafe(32)
