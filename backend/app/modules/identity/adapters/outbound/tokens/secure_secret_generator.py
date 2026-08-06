import secrets


class SecureSecretGenerator:
    def generate(self) -> str:
        return secrets.token_urlsafe(32)
