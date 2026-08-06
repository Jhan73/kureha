from typing import Protocol

from app.modules.identity.domain.user_account import UserAccount


class UserDirectoryPort(Protocol):
    async def find_by_email(self, tenant_id: str, email: str) -> UserAccount | None: ...

    async def find_by_auth_subject(self, tenant_id: str, auth_subject: str) -> UserAccount | None: ...

    async def get_by_id(self, tenant_id: str, user_id: str) -> UserAccount | None: ...

    async def link_auth_subject(
        self, tenant_id: str, user_id: str, *, auth_subject: str, email_verified: bool
    ) -> UserAccount: ...

    async def provision_patient_user(
        self, tenant_id: str, *, site_id: str, email: str, auth_subject: str, email_verified: bool
    ) -> UserAccount: ...

    async def provision_staff_user(
        self,
        tenant_id: str,
        *,
        site_id: str,
        role: str,
        email: str,
        auth_subject: str,
        email_verified: bool,
        professional_id: str | None = None,
    ) -> UserAccount: ...
