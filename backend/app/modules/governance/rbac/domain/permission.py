from typing import NewType

# 'resource:action', e.g. 'appointment:create'.
ActionKey = NewType("ActionKey", str)


class PermissionPolicy:
    """Deny-by-default: user override wins, else role grant, else deny."""

    @staticmethod
    def resolve(*, user_override: bool | None, role_grant: bool | None) -> bool:
        if user_override is not None:
            return user_override
        if role_grant is not None:
            return role_grant
        return False
