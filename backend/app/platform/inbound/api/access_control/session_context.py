"""`set_session_context` (design.md §4.2, tasks.md task 5.1): emits the
`SET LOCAL app.*` GUCs every RLS policy reads, from a resolved `LiveActor`.
Mirrors `tests/rls/helpers.py::set_app_context` (see that helper's docstring:
"Phase 5's access-control middleware needs the same treatment when it starts
emitting these GUCs for real") -- production code and the RLS test suite
project the SAME six GUCs the SAME way.

**Why literal string interpolation, not bind parameters:** `SET`/`SET LOCAL`
do not accept bind parameters over the extended query protocol (Postgres
requires a literal in the command itself). This is safe here ONLY because
every value embedded is either a UUID that just came back from a `users`/
`staff_members` row read by `PostgresLiveActorResolver` (never raw request
input) or the nil-UUID sentinel constant below -- never interpolate a
caller-supplied string into this function.

**Why a single `DO $$ ... $$` block, not six separate `execute()` calls:**
asyncpg's SQLAlchemy async dialect always executes over the extended query
protocol (PREPARE-then-EXECUTE), and Postgres rejects more than one
top-level command inside a single prepared statement ("cannot insert
multiple commands into a prepared statement") -- confirmed empirically:
`conn.execute(text("SET LOCAL a = '1'; SET LOCAL b = '2';"))` fails
outright, and so does the same string via `exec_driver_sql`, since both
paths go through the same asyncpg PREPARE step. Wrapping all six `SET
LOCAL` statements inside one anonymous `DO $$ ... $$` block makes them ONE
command from the parser's point of view (a single `DoStmt`), which the
extended protocol accepts. `SET LOCAL` executed from inside a plain `DO`
block with no exception handler (so no implicit subtransaction) still
scopes to the ENCLOSING transaction exactly the same as if it had been
issued directly -- proven by `test_session_context.py`'s existing
`rls_conn`-backed assertions, which read the GUCs back via a plain
`current_setting()` query on the same connection after this function
returns. This drops the round-trip count from six `conn.execute()` calls to
one.

**Why the nil-UUID sentinel for absent `patient_id`/`professional_id`:** a
literal empty string cannot satisfy every policy's `::uuid` cast
(`''::uuid` raises `invalid input syntax`), and Postgres's single-argument
`current_setting('app.x')` raises `unrecognized configuration parameter` if
a GUC was NEVER set at all in the session -- which happens because RLS
evaluates every permissive policy for a command, including ones for roles
that don't apply (e.g. `patients_self` while querying as `reception`). The
nil UUID satisfies both constraints and is guaranteed to never equal a real
`gen_random_uuid()`-generated id."""

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
