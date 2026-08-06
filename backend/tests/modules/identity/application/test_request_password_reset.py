import pytest

from app.modules.identity.application.use_cases.request_password_reset import RequestPasswordReset


class _FakeAuth:
    def __init__(self) -> None:
        self.requested_emails: list[str] = []
        self.redirect_urls: list[str] = []

    async def verify_password(self, email, password):
        raise NotImplementedError

    async def verify_federated(self, provider, id_token):
        raise NotImplementedError

    async def start_password_reset(self, email: str, redirect_to: str) -> None:
        self.requested_emails.append(email)
        self.redirect_urls.append(redirect_to)

    async def invite_user(self, email, redirect_to):
        raise NotImplementedError

    async def complete_password_reset(self, recovery_token, new_password):
        raise NotImplementedError


_REDIRECT_URL = "https://app.example.com"


@pytest.mark.asyncio
async def test_forwards_the_email_to_the_auth_port() -> None:
    auth = _FakeAuth()
    use_case = RequestPasswordReset(auth, redirect_url=_REDIRECT_URL)

    await use_case.execute("a@example.com")

    assert auth.requested_emails == ["a@example.com"]


@pytest.mark.asyncio
async def test_forwards_the_configured_redirect_url_to_the_auth_port() -> None:
    auth = _FakeAuth()
    use_case = RequestPasswordReset(auth, redirect_url=_REDIRECT_URL)

    await use_case.execute("a@example.com")

    assert auth.redirect_urls == [_REDIRECT_URL]
