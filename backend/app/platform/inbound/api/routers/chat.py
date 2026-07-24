"""Chat router (design.md §8.6, tasks.md task 11.7): `POST /chat` --
non-streaming invocation of `build_graph()` (SSE streaming is task 12.1, a
LATER phase; a plain `await graph.ainvoke(...)` is enough here per this
task's own instructions).

**`thread_id` ownership validation (design.md §8.6) -- the entire point of
this router, not an afterthought.** The request body accepts an OPTIONAL
`client_random_uuid`; if absent, the server generates one
(`design.md: "Si el cliente no envia client_random_uuid, el server genera
uno por request"`). The server then ASSEMBLES the real `thread_id` as
`f"{tenant_id}:{user_id}:{client_random}"` from the AUTHENTICATED actor's
OWN resolved identity (`get_tenant_context`/`get_live_actor`, both populated
by `AccessControlMiddleware` from the caller's own verified access token --
see `access_control/dependencies.py`'s own docstring) -- NEVER from anything
in the request body. An attacker who guesses another session's
`client_random_uuid` still cannot construct that session's real `thread_id`
without ALSO holding that session's own valid access token, since
`tenant_id`/`user_id` come exclusively from server-side token verification,
never from client-supplied input.

**Runs BEHIND `AccessControlMiddleware`, deliberately** -- same posture as
`scheduling.py`/`calendar_oauth.py`: uses the request's already-open,
RLS-scoped `request.state.db_conn` for every business/governance use case
`build_graph()`'s nodes need, and the resolved `TenantContext`/`LiveActor`
to build `RequestContext`. No dedicated RBAC check here -- exactly like
every other router in this package, RBAC is enforced INSIDE the graph
itself (`rbac_gate`), not re-checked at the router boundary.

**`channel` -- `staff_copilot` for any non-`patient` role, `patient_chat`
otherwise.** design.md §8.6 describes both channels sharing this exact
endpoint shape/mechanism ("mismo patron... la unica diferencia es que el
`user_id` en la key es el del staff... y el `RequestContext` incluye `role`
y `site_id` del staff en lugar de `patient_id`") -- `LiveActor.role` is
already resolved by the middleware, so this router derives `channel`
directly from it rather than requiring the client to declare which one it
is (a client-declared channel would be one more value this router would
have to distrust and re-derive anyway).

**Only `request_ctx`/`channel`/`channel_message` are passed as `graph.
ainvoke()`'s input -- a DELIBERATE partial `KurehaState` update, never a
full one.** LangGraph applies every key PRESENT in an `ainvoke` input dict
as an unconditional overwrite of the checkpointed value (same "last write
wins, no reducer" semantics as any node's own return dict) -- a full
`KurehaState` literal with `"proposed_action": None` would WIPE turn N's
pending `proposed_action` before `route_from_start` ever got to read it,
breaking the entire turn-N/turn-N+1 confirmation mechanism design.md §8.9
depends on. `test_build_graph.py`'s own confirmation-round-trip test proves
this partial-dict shape is what actually works against the real compiled
graph."""

import uuid

from fastapi import APIRouter, Depends
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from app.composition_root import open_checkpointer_connection
from app.platform.inbound.api.access_control.dependencies import get_db_conn, get_live_actor, get_tenant_context
from app.platform.inbound.api.access_control.live_actor import LiveActor
from app.platform.inbound.graph.build_graph import build_graph
from app.platform.inbound.graph.state import RequestContext
from app.shared_kernel.tenant_context import TenantContext

router = APIRouter(prefix="/chat", tags=["chat"])

_STAFF_ROLES = frozenset({"reception", "professional", "admin"})


class ChatRequest(BaseModel):
    message: str
    client_random_uuid: str | None = None


class ChatResponse(BaseModel):
    response_text: str | None
    suggestions: list[str] | None
    confirmation: str | None


def _channel_for(role: str) -> str:
    return "staff_copilot" if role in _STAFF_ROLES else "patient_chat"


@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    live_actor: LiveActor = Depends(get_live_actor),
    conn: AsyncConnection = Depends(get_db_conn),
) -> ChatResponse:
    client_random = payload.client_random_uuid or str(uuid.uuid4())
    # `tenant_id`/`user_id` come ONLY from the server-verified actor -- see
    # this module's own docstring for why this is the entire security
    # property design.md §8.6 asks for.
    thread_id = f"{ctx.tenant_id}:{live_actor.user_id}:{client_random}"

    request_ctx = RequestContext(
        tenant_id=ctx.tenant_id,
        role=ctx.role,
        site_id=ctx.site_id,
        user_id=live_actor.user_id,
        patient_id=live_actor.patient_id,
        professional_id=live_actor.professional_id,
    )
    channel = _channel_for(ctx.role)

    async with open_checkpointer_connection(ctx.tenant_id) as checkpointer_conn:
        checkpointer = AsyncPostgresSaver(checkpointer_conn)
        graph = await build_graph(conn, checkpointer=checkpointer)

        result = await graph.ainvoke(
            {"request_ctx": request_ctx, "channel": channel, "channel_message": payload.message},
            {"configurable": {"thread_id": thread_id}},
        )

    return ChatResponse(
        response_text=result.get("response_text"),
        suggestions=result.get("suggestions"),
        confirmation=result.get("confirmation"),
    )
