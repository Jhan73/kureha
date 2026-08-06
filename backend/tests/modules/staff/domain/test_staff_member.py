from datetime import datetime, timezone

import pytest

from app.modules.staff.domain.staff_member import OperationalRole, StaffMember, StaffStatus

_ACTIVATED_AT = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)


def _staff_member(*, status: StaffStatus = StaffStatus.ACTIVE, deactivated_at: datetime | None = None) -> StaffMember:
    return StaffMember(
        id="sm1",
        tenant_id="t1",
        site_id="s1",
        user_id=None,
        professional_id="pr1",
        name="Ana Torres",
        operational_role=OperationalRole.PROFESSIONAL,
        status=status,
        activated_at=_ACTIVATED_AT,
        deactivated_at=deactivated_at,
    )


def test_is_active_when_status_is_active() -> None:
    assert _staff_member(status=StaffStatus.ACTIVE).is_active is True


def test_is_not_active_when_status_is_inactive() -> None:
    assert _staff_member(status=StaffStatus.INACTIVE).is_active is False


@pytest.mark.parametrize("role", [OperationalRole.RECEPTION, OperationalRole.PROFESSIONAL, OperationalRole.ADMIN])
def test_operational_role_accepts_every_catalog_value(role: OperationalRole) -> None:
    staff = _staff_member()
    staff = StaffMember(
        id=staff.id,
        tenant_id=staff.tenant_id,
        site_id=staff.site_id,
        user_id=staff.user_id,
        professional_id=staff.professional_id,
        name=staff.name,
        operational_role=role,
        status=staff.status,
        activated_at=staff.activated_at,
        deactivated_at=staff.deactivated_at,
    )
    assert staff.operational_role is role
