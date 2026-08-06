from app.modules.governance.rbac.domain.permission import PermissionPolicy


def test_user_override_allow_wins_over_role_deny() -> None:
    assert PermissionPolicy.resolve(user_override=True, role_grant=False) is True


def test_user_override_deny_wins_over_role_allow() -> None:
    assert PermissionPolicy.resolve(user_override=False, role_grant=True) is False


def test_role_grant_applies_when_no_user_override() -> None:
    assert PermissionPolicy.resolve(user_override=None, role_grant=True) is True
    assert PermissionPolicy.resolve(user_override=None, role_grant=False) is False


def test_deny_by_default_when_neither_is_set() -> None:
    assert PermissionPolicy.resolve(user_override=None, role_grant=None) is False
