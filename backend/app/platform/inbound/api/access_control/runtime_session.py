"""`EngineRuntimeSession`: production `RuntimeSessionPort` impl (design.md
§4.2, tasks.md task 5.1). Opens the request-scoped connection from
`app.db.runtime_engine` (the `app_runtime` role RLS is actually enforced
against -- see `app/db.py`'s module docstring), begins a transaction, and
projects `SET LOCAL app.*` via `set_session_context` -- this is the
"Recién entonces se emiten los SET LOCAL app.*" step design.md §4.2
describes, made concrete.

Every downstream adapter in this codebase (`PostgresAuditLog`,
`PermissionService`, the consent/RLS-scoped repositories, etc.) already
documents the same expectation: "takes an already-open `AsyncConnection`
... with the request's GUCs already set" -- this class is what satisfies
that expectation for the request pipeline, once the composition root (task
10.2, not yet built) wires `AccessControlMiddleware`'s `runtime_session`
dependency to an instance of this class."""

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
