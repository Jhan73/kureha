"""`AuthPort` (design.md §17.1): mirrors `CalendarSyncPort`'s shape -- a
driven port isolating the identity module's domain/use cases from the IdP
vendor (Supabase Auth/GoTrue, ADR-14). Implemented in MVP by
`SupabaseAuthAdapter` (adapters/outbound/auth/supabase_auth_adapter.py).

Raises `app.modules.identity.domain.errors.InvalidCredentialsError` on any
verification failure -- both methods, regardless of cause (bad password,
unknown email, expired/invalid id_token), so callers never learn *why* it
failed (spec `user-authentication` -> "Wrong password rejected without
enumeration")."""

from typing import Literal, Protocol

from app.modules.identity.domain.authn_result import AuthnResult


class AuthPort(Protocol):
    async def verify_password(self, email: str, password: str) -> AuthnResult: ...

    async def verify_federated(self, provider: Literal["google"], id_token: str) -> AuthnResult: ...

    async def start_password_reset(self, email: str) -> None: ...
