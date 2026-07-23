"""Task 8.2: `DeactivateStaff` use case -- `authorize` first, load the
existing staff member, deactivate (status flip, never delete), and audit.
Fakes only, no DB."""

from datetime import datetime, timezone

import pytest

from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType
from app.modules.governance.rbac.application.use_cases.authorize_action import (
    ActionNotPermittedError,
    AuthorizeAction,
)
from app.modules.staff.application.use_cases.deactivate_staff import DeactivateStaff
from app.modules.staff.domain.errors import StaffMemberNotFoundError
from app.modules.staff.domain.staff_member import OperationalRole, StaffMember, StaffStatus
from app.shared_kernel.tenant_context import TenantContext

_ACTIVATED_AT = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
_DEACTIVATED_AT = datetime(2026, 8, 2, 9, 0, tzinfo=timezone.utc)


class _FakeAuthorizationPort:
    def __init__(self, *, allowed: bool = True) -> None:
        self._allowed = allowed
        self.checked: list[str] = []

    async def is_allowed(self, ctx, action) -> bool:
        self.checked.append(action)
        return self._allowed

    async def list_allowed_actions(self, ctx):
        raise NotImplementedError


def _staff(*, status: StaffStatus = StaffStatus.ACTIVE) -> StaffMember:
    return StaffMember(
        id="sm-1",
        tenant_id="t1",
        site_id="s1",
        user_id=None,
        professional_id="pr1",
        name="Ana Torres",
        operational_role=OperationalRole.PROFESSIONAL,
        status=status,
        activated_at=_ACTIVATED_AT,
    )


class _FakeStaffRepository:
    def __init__(self, *, existing: StaffMember | None) -> None:
        self._existing = existing
        self.deactivated: list[str] = []

    async def create_staff_member(self, *args, **kwargs):
        raise NotImplementedError

    async def get_staff_member(self, tenant_id, staff_member_id) -> StaffMember | None:
        return self._existing

    async def deactivate_staff_member(self, tenant_id, staff_member_id) -> StaffMember:
        self.deactivated.append(staff_member_id)
        return StaffMember(
            id=staff_member_id,
            tenant_id=tenant_id,
            site_id=self._existing.site_id,
            user_id=self._existing.user_id,
            professional_id=self._existing.professional_id,
            name=self._existing.name,
            operational_role=self._existing.operational_role,
            status=StaffStatus.INACTIVE,
            activated_at=self._existing.activated_at,
            deactivated_at=_DEACTIVATED_AT,
        )


class _FakeAuditLog:
    def __init__(self) -> None:
        self.recorded: list = []

    async def record(self, entry) -> str:
        self.recorded.append(entry)
        return "audit-1"


def _ctx() -> TenantContext:
    return TenantContext(tenant_id="t1", role="admin", site_id="s1", actor_id="u1")


async def test_authorize_is_checked_first() -> None:
    authorization = _FakeAuthorizationPort(allowed=False)
    use_case = DeactivateStaff(AuthorizeAction(authorization), _FakeStaffRepository(existing=None), _FakeAuditLog())

    with pytest.raises(ActionNotPermittedError):
        await use_case.execute(_ctx(), staff_member_id="sm-1")

    assert authorization.checked == ["staff:deactivate"]


async def test_missing_staff_member_raises_not_found() -> None:
    use_case = DeactivateStaff(
        AuthorizeAction(_FakeAuthorizationPort()), _FakeStaffRepository(existing=None), _FakeAuditLog()
    )

    with pytest.raises(StaffMemberNotFoundError):
        await use_case.execute(_ctx(), staff_member_id="sm-1")


async def test_happy_path_deactivates_and_audits() -> None:
    staff_repository = _FakeStaffRepository(existing=_staff())
    audit = _FakeAuditLog()
    use_case = DeactivateStaff(AuthorizeAction(_FakeAuthorizationPort()), staff_repository, audit)

    deactivated = await use_case.execute(_ctx(), staff_member_id="sm-1")

    assert deactivated.status == StaffStatus.INACTIVE
    assert deactivated.deactivated_at == _DEACTIVATED_AT
    assert staff_repository.deactivated == ["sm-1"]
    assert len(audit.recorded) == 1
    entry = audit.recorded[0]
    assert entry.action == AuditAction.STAFF_DEACTIVATE
    assert entry.actor_type == AuditActorType.USER
    assert entry.object_type == "staff_member"
    assert entry.object_id == "sm-1"
