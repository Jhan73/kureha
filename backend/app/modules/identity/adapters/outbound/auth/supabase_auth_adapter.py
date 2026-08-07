from typing import Literal

import httpx

from app.modules.identity.domain.authn_result import AuthnResult
from app.modules.identity.domain.errors import InvalidCredentialsError

_TOKEN_PATH = "/auth/v1/token"
_RECOVER_PATH = "/auth/v1/recover"
_INVITE_PATH = "/auth/v1/invite"
_USER_PATH = "/auth/v1/user"


class SupabaseAuthAdapter:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        http_client: httpx.AsyncClient,
        secret_key: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._secret_key = secret_key
        self._http = http_client

    async def verify_password(self, email: str, password: str) -> AuthnResult:
        response = await self._http.post(
            f"{self._base_url}{_TOKEN_PATH}",
            params={"grant_type": "password"},
            headers=self._headers(),
            json={"email": email, "password": password},
        )
        if response.status_code >= 400:
            raise InvalidCredentialsError()
        return self._to_authn_result(response.json(), provider="password")

    async def verify_federated(self, provider: Literal["google"], id_token: str) -> AuthnResult:
        response = await self._http.post(
            f"{self._base_url}{_TOKEN_PATH}",
            params={"grant_type": "id_token"},
            headers=self._headers(),
            json={"provider": provider, "id_token": id_token},
        )
        if response.status_code >= 400:
            raise InvalidCredentialsError()
        return self._to_authn_result(response.json(), provider=provider)

    async def start_password_reset(self, email: str, redirect_to: str) -> None:
        await self._http.post(
            f"{self._base_url}{_RECOVER_PATH}",
            headers=self._headers(),
            json={"email": email, "redirect_to": redirect_to},
        )

    async def invite_user(self, email: str, redirect_to: str) -> AuthnResult:
        if not self._secret_key:
            raise RuntimeError(
                "SupabaseAuthAdapter.invite_user requires secret_key, none was configured"
            )
        response = await self._http.post(
            f"{self._base_url}{_INVITE_PATH}",
            headers=self._admin_headers(),
            json={"email": email, "redirect_to": redirect_to},
        )
        response.raise_for_status()
        return self._to_authn_result_bare(response.json(), provider="password")

    async def complete_password_reset(self, recovery_token: str, new_password: str) -> AuthnResult:
        response = await self._http.put(
            f"{self._base_url}{_USER_PATH}",
            headers=self._recovery_headers(recovery_token),
            json={"password": new_password},
        )
        if response.status_code >= 400:
            raise InvalidCredentialsError()
        return self._to_authn_result_bare(response.json(), provider="password")

    def _headers(self) -> dict[str, str]:
        return {"apikey": self._api_key, "Content-Type": "application/json"}

    def _admin_headers(self) -> dict[str, str]:
        return {
            "apikey": self._secret_key,
            "Authorization": f"Bearer {self._secret_key}",
            "Content-Type": "application/json",
        }

    def _recovery_headers(self, recovery_token: str) -> dict[str, str]:
        return {
            "apikey": self._api_key,
            "Authorization": f"Bearer {recovery_token}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _to_authn_result(payload: dict, *, provider: Literal["password", "google"]) -> AuthnResult:
        user = payload["user"]
        return AuthnResult(
            subject=user["id"],
            email=user["email"],
            email_verified=user.get("email_confirmed_at") is not None,
            provider=provider,
        )

    @staticmethod
    def _to_authn_result_bare(user: dict, *, provider: Literal["password", "google"]) -> AuthnResult:
        return AuthnResult(
            subject=user["id"],
            email=user["email"],
            email_verified=user.get("email_confirmed_at") is not None,
            provider=provider,
        )
