from app.modules.governance.audit.application.ports.driven.audit_log import AuditLogPort
from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.modules.identity.application.ports.driven.auth import AuthPort
from app.modules.identity.application.ports.driven.user_directory import UserDirectoryPort
from app.modules.identity.domain.errors import EmailAlreadyRegisteredError
from app.modules.identity.domain.user_account import UserAccount
from app.shared_kernel.errors import ValidationError

_STAFF_ROLES = frozenset({"reception", "professional", "admin"})


class ProvisionStaffIdentity:
    def __init__(
        self, auth: AuthPort, user_directory: UserDirectoryPort, audit_log: AuditLogPort, invite_redirect_url: str
    ) -> None:
        self._auth = auth
        self._user_directory = user_directory
        self._audit_log = audit_log
        self._invite_redirect_url = invite_redirect_url

    async def execute(
        self,
        tenant_id: str,
        *,
        site_id: str,
        email: str,
        role: str,
        professional_id: str | None = None,
        actor_id: str | None = None,
    ) -> UserAccount:
        if role not in _STAFF_ROLES:
            raise ValidationError(f"role must be one of {sorted(_STAFF_ROLES)}, got {role!r}")
        if role == "professional" and professional_id is None:
            raise ValidationError("professional_id is required when role is 'professional'")

        existing = await self._user_directory.find_by_email(tenant_id, email)
        if existing is not None:
            raise EmailAlreadyRegisteredError(f"email already registered: {email}")

        authn = await self._auth.invite_user(email, redirect_to=self._invite_redirect_url)

        user = await self._user_directory.provision_staff_user(
            tenant_id,
            site_id=site_id,
            role=role,
            email=email,
            auth_subject=authn.subject,
            email_verified=authn.email_verified,
            professional_id=professional_id,
        )

        await self._audit_log.record(
            AuditEntry(
                tenant_id=tenant_id,
                site_id=site_id,
                actor_id=actor_id,
                actor_type=AuditActorType.USER,
                action=AuditAction.AUTH_CREDENTIAL_CREATED,
                object_type="user",
                object_id=user.id,
                payload={"email": email, "role": role},
            )
        )
        return user
