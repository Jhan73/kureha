"""`Permission`/`PermissionPolicy` domain (design.md §5.1/§5.2). Pure
value objects and a stateless precedence rule -- no IO."""

from typing import NewType

# 'resource:action' format (design.md §5.1), e.g. 'appointment:create'.
ActionKey = NewType("ActionKey", str)


class PermissionPolicy:
    """Deny-by-default, more-specific-wins precedence (design.md §5.2):

    1. user override (`user_permissions`: allow or explicit deny) -- wins if
       a row exists, regardless of its value.
    2. role grant (`role_permissions`, tenant-scoped) -- applies only if no
       user override row exists.
    3. no row at all -- DENIED (deny-by-default, never ambiguous).
    """

    @staticmethod
    def resolve(*, user_override: bool | None, role_grant: bool | None) -> bool:
        if user_override is not None:
            return user_override
        if role_grant is not None:
            return role_grant
        return False
