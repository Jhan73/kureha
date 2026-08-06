from dataclasses import dataclass

from app.modules.identity.domain.user_account import UserAccount


@dataclass(frozen=True, slots=True)
class LoginResult:
    access_token: str
    refresh_token: str
    user: UserAccount


@dataclass(frozen=True, slots=True)
class AccountLinkRequired:
    existing_user_id: str
    email: str
    pending_subject: str
    email_verified: bool
