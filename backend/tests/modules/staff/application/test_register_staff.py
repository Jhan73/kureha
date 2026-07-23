"""Task 8.2: `RegisterStaff` use case -- `authorize(ctx, action)` first
(design.md §5.3), then create the staff member and audit. Fakes only, no
DB."""

from datetime import datetime, timezone

import pytest

from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType
from app.modules.governance.rbac.application.use_cases.authorize_action import (
    ActionNotPermittedError,
    AuthorizeAction,
)
from app.modules.staff.application.use_cases.register_staff import RegisterStaff
from app.modules.staff.domain.staff_member import OperationalRole, StaffMember, StaffStatus
from app.shared_kernel.tenant_context import TenantContext

_ACTIVATED_AT = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)


class _FakeAuthorizationPort:
    def __init__(self, *, allowed: bool = True) -> None:
        self._allowed = allowed
        self.checked: list[str] = []

    async def is_allowed(self, ctx, action) -> bool:
        self.checked.append(action)
        return self._allowed

    async def list_allowed_actions(self, ctx):
        raise NotImplementedError


class _FakeStaffRepository:
    def __init__(self) -> None:
        self.created: list[dict] = []

    async def create_staff_member(
        self, tenant_id, *, site_id, name, operational_role, user_id=None, professional_id=None
    ) -> StaffMember:
        self.created.append(
            {
                "tenant_id": tenant_id,
                "site_id": site_id,
                "name": name,
                "operational_role": operational_role,
                "user_id": user_id,
                "professional_id": professional_id,
            }
        )
        return StaffMember(
            id="sm-1",
            tenant_id=tenant_id,
            site_id=site_id,
            user_id=user_id,
            professional_id=professional_id,
            name=name,
            operational_role=operational_role,
            status=StaffStatus.ACTIVE,
            activated_at=_ACTIVATED_AT,
        )

    async def get_staff_member(self, tenant_id, staff_member_id):
        raise NotImplementedError

    async def deactivate_staff_member(self, tenant_id, staff_member_id):
        raise NotImplementedError


class _FakeAuditLog:
    def __init__(self) -> None:
        self.recorded: list = []

    async def record(self, entry) -> str:
        self.recorded.append(entry)
        return "audit-1"


def _ctx() -> TenantContext:
    return TenantContext(tenant_id="t1", role="admin", site_id="s1", actor_id="u1")


async def test_authorize_is_checked_before_anything_else() -> None:
    authorization = _FakeAuthorizationPort(allowed=False)
    use_case = RegisterStaff(AuthorizeAction(authorization), _FakeStaffRepository(), _FakeAuditLog())

    with pytest.raises(ActionNotPermittedError):
        await use_case.execute(
            _ctx(), site_id="s1", name="Ana Torres", operational_role=OperationalRole.PROFESSIONAL
        )

    assert authorization.checked == ["staff:register"]


async def test_happy_path_creates_and_audits() -> None:
    authorization = _FakeAuthorizationPort(allowed=True)
    staff_repository = _FakeStaffRepository()
    audit = _FakeAuditLog()
    use_case = RegisterStaff(AuthorizeAction(authorization), staff_repository, audit)

    staff = await use_case.execute(
        _ctx(),
        site_id="s1",
        name="Ana Torres",
        operational_role=OperationalRole.PROFESSIONAL,
        professional_id="pr1",
    )

    assert staff.id == "sm-1"
    assert staff.status == StaffStatus.ACTIVE
    assert staff_repository.created == [
        {
            "tenant_id": "t1",
            "site_id": "s1",
            "name": "Ana Torres",
            "operational_role": OperationalRole.PROFESSIONAL,
            "user_id": None,
            "professional_id": "pr1",
        }
    ]
    assert len(audit.recorded) == 1
    entry = audit.recorded[0]
    assert entry.tenant_id == "t1"
    assert entry.site_id == "s1"
    assert entry.actor_id == "u1"
    assert entry.actor_type == AuditActorType.USER
    assert entry.action == AuditAction.STAFF_REGISTER
    assert entry.object_type == "staff_member"
    assert entry.object_id == "sm-1"
