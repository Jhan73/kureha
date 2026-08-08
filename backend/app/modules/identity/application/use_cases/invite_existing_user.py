from app.modules.governance.audit.application.ports.driven.audit_log import AuditLogPort
from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.modules.identity.application.ports.driven.auth import AuthPort
from app.modules.identity.application.ports.driven.user_directory import UserDirectoryPort
from app.modules.identity.domain.errors import CredentialInvitationFailedError
from app.modules.identity.domain.user_account import UserAccount


class InviteExistingUser:
    """Sends a Supabase invite for a user row that was already provisioned DB-first, with no auth_subject yet."""

    def __init__(
        self, auth: AuthPort, user_directory: UserDirectoryPort, audit_log: AuditLogPort, invite_redirect_url: str
    ) -> None:
        self._auth = auth
        self._user_directory = user_directory
        self._audit_log = audit_log
        self._invite_redirect_url = invite_redirect_url

    async def execute(self, tenant_id: str, *, user_id: str, site_id: str, email: str) -> UserAccount:
        try:
            authn = await self._auth.invite_user(email, redirect_to=self._invite_redirect_url)
        except Exception as exc:
            raise CredentialInvitationFailedError(f"invite delivery failed for {email!r}: {exc}") from exc

        user = await self._user_directory.link_auth_subject(
            tenant_id, user_id, auth_subject=authn.subject, email_verified=authn.email_verified
        )

        await self._audit_log.record(
            AuditEntry(
                tenant_id=tenant_id,
                site_id=site_id,
                actor_type=AuditActorType.SYSTEM,
                action=AuditAction.AUTH_CREDENTIAL_CREATED,
                object_type="user",
                object_id=user.id,
                payload={"email": email},
            )
        )
        return user
