"""Task 8.2: `EditShift` use case -- `authorize` first, confirm the shift
exists, edit it (the DB's `EXCLUDE USING gist` remains the anti-overlap
floor), and audit. Fakes only, no DB."""

from datetime import datetime, timezone

import pytest

from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType
from app.modules.governance.rbac.application.use_cases.authorize_action import (
    ActionNotPermittedError,
    AuthorizeAction,
)
from app.modules.staff.application.use_cases.edit_shift import EditShift
from app.modules.staff.domain.errors import ShiftNotFoundError
from app.modules.staff.domain.shift import Shift
from app.shared_kernel.tenant_context import TenantContext

_T0 = datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc)
_T1 = datetime(2026, 8, 3, 14, 0, tzinfo=timezone.utc)
_T2 = datetime(2026, 8, 3, 15, 0, tzinfo=timezone.utc)


class _FakeAuthorizationPort:
    def __init__(self, *, allowed: bool = True) -> None:
        self._allowed = allowed
        self.checked: list[str] = []

    async def is_allowed(self, ctx, action) -> bool:
        self.checked.append(action)
        return self._allowed

    async def list_allowed_actions(self, ctx):
        raise NotImplementedError


def _shift() -> Shift:
    return Shift(id="sh-1", tenant_id="t1", site_id="s1", staff_member_id="sm-1", starts_at=_T0, ends_at=_T1)


class _FakeShiftRepository:
    def __init__(self, *, existing: Shift | None) -> None:
        self._existing = existing
        self.edited: list[dict] = []

    async def create_shift(self, *args, **kwargs):
        raise NotImplementedError

    async def get_shift(self, tenant_id, shift_id) -> Shift | None:
        return self._existing

    async def edit_shift(self, tenant_id, shift_id, *, starts_at, ends_at) -> Shift:
        self.edited.append({"shift_id": shift_id, "starts_at": starts_at, "ends_at": ends_at})
        return Shift(
            id=shift_id, tenant_id=tenant_id, site_id=self._existing.site_id,
            staff_member_id=self._existing.staff_member_id, starts_at=starts_at, ends_at=ends_at,
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
    use_case = EditShift(AuthorizeAction(authorization), _FakeShiftRepository(existing=None), _FakeAuditLog())

    with pytest.raises(ActionNotPermittedError):
        await use_case.execute(_ctx(), shift_id="sh-1", starts_at=_T1, ends_at=_T2)

    assert authorization.checked == ["shift:edit"]


async def test_missing_shift_raises_not_found() -> None:
    use_case = EditShift(AuthorizeAction(_FakeAuthorizationPort()), _FakeShiftRepository(existing=None), _FakeAuditLog())

    with pytest.raises(ShiftNotFoundError):
        await use_case.execute(_ctx(), shift_id="sh-1", starts_at=_T1, ends_at=_T2)


async def test_happy_path_edits_and_audits() -> None:
    shift_repository = _FakeShiftRepository(existing=_shift())
    audit = _FakeAuditLog()
    use_case = EditShift(AuthorizeAction(_FakeAuthorizationPort()), shift_repository, audit)

    edited = await use_case.execute(_ctx(), shift_id="sh-1", starts_at=_T1, ends_at=_T2)

    assert edited.starts_at == _T1
    assert edited.ends_at == _T2
    assert shift_repository.edited == [{"shift_id": "sh-1", "starts_at": _T1, "ends_at": _T2}]
    assert len(audit.recorded) == 1
    entry = audit.recorded[0]
    assert entry.action == AuditAction.SHIFT_EDIT
    assert entry.actor_type == AuditActorType.USER
    assert entry.object_type == "shift"
    assert entry.object_id == "sh-1"
    assert entry.payload == {"staff_member_id": "sm-1"}
