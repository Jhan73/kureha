"""Task 8.2: `CreateShift` use case -- `authorize` first, confirm the staff
member exists and is assignable (`StaffPolicy.is_assignable`), create the
shift, and audit. Fakes only, no DB."""

from datetime import datetime, timezone

import pytest

from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType
from app.modules.governance.rbac.application.use_cases.authorize_action import (
    ActionNotPermittedError,
    AuthorizeAction,
)
from app.modules.staff.application.use_cases.create_shift import CreateShift
from app.modules.staff.domain.errors import StaffMemberNotActiveError, StaffMemberNotFoundError
from app.modules.staff.domain.shift import Shift
from app.modules.staff.domain.staff_member import OperationalRole, StaffMember, StaffStatus
from app.shared_kernel.tenant_context import TenantContext

_T0 = datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc)
_T1 = datetime(2026, 8, 3, 14, 0, tzinfo=timezone.utc)
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

    async def create_staff_member(self, *args, **kwargs):
        raise NotImplementedError

    async def get_staff_member(self, tenant_id, staff_member_id) -> StaffMember | None:
        return self._existing

    async def deactivate_staff_member(self, tenant_id, staff_member_id):
        raise NotImplementedError


class _FakeShiftRepository:
    def __init__(self) -> None:
        self.created: list[dict] = []

    async def create_shift(self, tenant_id, *, site_id, staff_member_id, starts_at, ends_at) -> Shift:
        self.created.append(
            {"tenant_id": tenant_id, "site_id": site_id, "staff_member_id": staff_member_id}
        )
        return Shift(
            id="sh-1", tenant_id=tenant_id, site_id=site_id, staff_member_id=staff_member_id,
            starts_at=starts_at, ends_at=ends_at,
        )

    async def get_shift(self, tenant_id, shift_id):
        raise NotImplementedError

    async def edit_shift(self, tenant_id, shift_id, *, starts_at, ends_at):
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
    use_case = CreateShift(
        AuthorizeAction(authorization), _FakeStaffRepository(existing=None), _FakeShiftRepository(), _FakeAuditLog()
    )

    with pytest.raises(ActionNotPermittedError):
        await use_case.execute(_ctx(), site_id="s1", staff_member_id="sm-1", starts_at=_T0, ends_at=_T1)

    assert authorization.checked == ["shift:create"]


async def test_missing_staff_member_raises_not_found() -> None:
    use_case = CreateShift(
        AuthorizeAction(_FakeAuthorizationPort()), _FakeStaffRepository(existing=None), _FakeShiftRepository(), _FakeAuditLog()
    )

    with pytest.raises(StaffMemberNotFoundError):
        await use_case.execute(_ctx(), site_id="s1", staff_member_id="sm-1", starts_at=_T0, ends_at=_T1)


async def test_inactive_staff_member_raises_not_active() -> None:
    use_case = CreateShift(
        AuthorizeAction(_FakeAuthorizationPort()),
        _FakeStaffRepository(existing=_staff(status=StaffStatus.INACTIVE)),
        _FakeShiftRepository(),
        _FakeAuditLog(),
    )

    with pytest.raises(StaffMemberNotActiveError):
        await use_case.execute(_ctx(), site_id="s1", staff_member_id="sm-1", starts_at=_T0, ends_at=_T1)


async def test_happy_path_creates_and_audits() -> None:
    shift_repository = _FakeShiftRepository()
    audit = _FakeAuditLog()
    use_case = CreateShift(
        AuthorizeAction(_FakeAuthorizationPort()), _FakeStaffRepository(existing=_staff()), shift_repository, audit
    )

    shift = await use_case.execute(_ctx(), site_id="s1", staff_member_id="sm-1", starts_at=_T0, ends_at=_T1)

    assert shift.id == "sh-1"
    assert shift_repository.created == [{"tenant_id": "t1", "site_id": "s1", "staff_member_id": "sm-1"}]
    assert len(audit.recorded) == 1
    entry = audit.recorded[0]
    assert entry.action == AuditAction.SHIFT_CREATE
    assert entry.actor_type == AuditActorType.USER
    assert entry.object_type == "shift"
    assert entry.object_id == "sh-1"
    assert entry.payload == {"staff_member_id": "sm-1"}
