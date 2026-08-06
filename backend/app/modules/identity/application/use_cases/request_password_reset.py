from app.modules.identity.application.ports.driven.auth import AuthPort


class RequestPasswordReset:
    def __init__(self, auth: AuthPort, redirect_url: str) -> None:
        self._auth = auth
        self._redirect_url = redirect_url

    async def execute(self, email: str) -> None:
        await self._auth.start_password_reset(email, redirect_to=self._redirect_url)
