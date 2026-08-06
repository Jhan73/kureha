from typing import Protocol

from app.platform.inbound.api.access_control.live_actor import LiveActor


class LiveActorResolverPort(Protocol):
    async def resolve(self, user_id: str) -> LiveActor | None:
        """Live actor for `user_id`, or None if no users row exists."""
        ...
