from dataclasses import dataclass
from typing import Literal

AuthProvider = Literal["password", "google"]


@dataclass(frozen=True, slots=True)
class AuthnResult:
    subject: str
    email: str
    email_verified: bool
    provider: AuthProvider
