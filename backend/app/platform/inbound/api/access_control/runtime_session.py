from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.platform.inbound.api.access_control.live_actor import LiveActor
from app.platform.inbound.api.access_control.session_context import set_session_context


class EngineRuntimeSession:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def begin(self, actor: LiveActor) -> AsyncConnection:
        conn = await self._engine.connect()
        try:
            await conn.begin()
            await set_session_context(conn, actor)
        except BaseException:
            await conn.close()
            raise
        return conn

    async def end(self, conn: AsyncConnection, *, commit: bool) -> None:
        try:
            if commit:
                await conn.commit()
            else:
                await conn.rollback()
        finally:
            await conn.close()
