from app.platform.inbound.api.access_control.live_actor import LiveActor


def _actor(**overrides) -> LiveActor:
    defaults = dict(
        user_id="u1",
        tenant_id="t1",
        site_id="s1",
        role="reception",
        status="active",
        patient_id=None,
        professional_id=None,
        staff_status=None,
    )
    defaults.update(overrides)
    return LiveActor(**defaults)


def test_active_user_with_no_staff_row_is_active() -> None:
    actor = _actor(status="active", staff_status=None)
    assert actor.is_active is True


def test_inactive_user_is_never_active_regardless_of_staff_status() -> None:
    actor = _actor(status="inactive", staff_status="active")
    assert actor.is_active is False


def test_active_user_with_inactive_staff_row_is_not_active() -> None:
    actor = _actor(status="active", staff_status="inactive")
    assert actor.is_active is False


def test_active_user_with_active_staff_row_is_active() -> None:
    actor = _actor(status="active", staff_status="active")
    assert actor.is_active is True


def test_inactive_user_with_no_staff_row_is_not_active() -> None:
    actor = _actor(status="inactive", staff_status=None)
    assert actor.is_active is False
