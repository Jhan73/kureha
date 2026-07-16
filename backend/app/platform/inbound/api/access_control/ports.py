"""`LiveActorResolverPort` (design.md §4.2, tasks.md task 5.1): resolves the
JWT's `sub` (a `users.id`) to a live `LiveActor` snapshot -- `users` LEFT
JOIN `staff_members`. Kept behind a port so the access-control middleware's
orchestration (deny/allow branching, GUC emission) can be unit-tested with a
fake, the same pattern every other driven port in this codebase follows."""

from typing import Protocol

from app.platform.inbound.api.access_control.live_actor import LiveActor


class LiveActorResolverPort(Protocol):
    async def resolve(self, user_id: str) -> LiveActor | None:
        """Returns the live actor for `user_id`, or `None` if no `users`
        row exists with that id at all (design.md §4.2: "un token sin
        `users` mapeable se rechaza y audita")."""
        ...
