"""`ProvisionStaffIdentity` use case (design.md §17 extension, staff-invite
batch): the identity-module half of `POST /staff/register`'s new invite
flow. Creates a fresh, authenticatable identity for a NEW staff member --
invites the email via Supabase (`AuthPort.invite_user`, no password ever
set/seen by the admin who registers them, per the product decision this
batch implements) and creates the corresponding `users`/`user_credentials`
rows (`UserDirectoryPort.provision_staff_user`).

Deliberately does NOT create the `staff_members` operational-registry row --
that remains `RegisterStaff`'s (staff module) job, unchanged. The router
(`platform/inbound/api/routers/staff.py`) calls THIS use case first to
obtain a `user_id`, then calls `RegisterStaff.execute(..., user_id=...)`
with it -- two separate use cases in two separate business modules, matching
backend/AGENTS.md's "business modules never import each other directly"
constraint (this module cannot import `staff.domain.staff_member
.OperationalRole`, hence `role: str`, not that enum -- see
`UserDirectoryPort.provision_staff_user`'s own docstring for the same
constraint reflected at the port layer).

**RBAC note:** this use case does NOT call `AuthorizeAction` itself (unlike
`RegisterStaff`, which does). The router explicitly authorizes
(`staff:register`) BEFORE calling this use case -- mirroring `scheduling.py`'s
`_require_authorized` precedent -- because this use case has REAL,
externally-visible side effects (a Supabase invite email is sent, a `users`
row is created) that must not happen for an unauthorized caller merely
because `RegisterStaff`'s own internal check would catch it AFTER the fact,
too late to undo either side effect.

`invite_redirect_url` (added this session, gap-closure fix -- see
`docs/supabase-setup.md` §6): unlike `RequestPasswordReset`, THIS use case
knows the identity being provisioned is always staff (`_STAFF_ROLES`), so
`composition_root.py`'s `build_provision_staff_identity` targets
`Settings.frontend_base_url` + `/staff/login` -- the closest real, existing
page a newly-invited staff member could land on today. Flagged, not
silently invented: no dedicated "complete your invite" page exists yet on
the frontend; a future task should build one and point this at it instead."""

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
            # users.professional_id IS NOT NULL when role='professional'
            # (migration 8fc0dc6f958d's CHECK constraint) -- validated here,
            # BEFORE ever calling Supabase, so a bad request never triggers
            # a real invite email for a provisioning attempt that would fail
            # anyway.
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
