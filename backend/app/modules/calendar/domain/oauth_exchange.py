from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthorizationCodeExchange:
    refresh_token: str
    google_email: str
    scope: str
