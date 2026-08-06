from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.platform.inbound.api.access_control.live_actor import LiveActor

_NIL_UUID = "00000000-0000-0000-0000-000000000000"
_GUC_COLUMNS = ("tenant_id", "site_id", "role", "user_id", "patient_id", "professional_id")


async def set_session_context(conn: AsyncConnection, actor: LiveActor) -> None:
    """Sets all six `app.*` GUCs for the lifetime of the current transaction
    on `conn`, from `actor`'s live-resolved fields -- `tenant_id`/`site_id`/
    `role`/`user_id` (always set, since a `LiveActor` always has them) and
    `patient_id`/`professional_id` (nil-UUID sentinel when absent)."""
    values = {
        "tenant_id": actor.tenant_id,
        "site_id": actor.site_id,
        "role": actor.role,
        "user_id": actor.user_id,
        "patient_id": actor.patient_id,
        "professional_id": actor.professional_id,
    }
    statements = "\n".join(
        f"SET LOCAL app.{column} = '{values[column] or _NIL_UUID}';" for column in _GUC_COLUMNS
    )
    await conn.execute(text(f"DO $$ BEGIN {statements} END $$;"))
