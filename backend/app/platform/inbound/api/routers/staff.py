"""Staff router (staff-invite batch, closing tasks.md task 15.2's flagged
gap: "no `staff.py` router exists"): `POST /staff/register`.

Runs BEHIND `AccessControlMiddleware` (authenticated, RLS-scoped, uses the
request's already-open `request.state.db_conn`), same shape as
`scheduling.py`. Mirrors that router's `_require_authorized` precedent
(explicit, router-level RBAC check BEFORE either use case runs) -- NOT
redundant here the way `scheduling.py`'s own docstring flags its own
duplication as "minor": `ProvisionStaffIdentity` (identity module) has REAL,
externally-visible, hard-to-undo side effects (a genuine Supabase invite
email is sent, a `users`/`user_credentials` row is created) that
`RegisterStaff`'s OWN internal `AuthorizeAction.execute()` call -- which
only runs SECOND, inside this handler, after those side effects already
happened -- would be too late to prevent. Explicitly authorizing
`staff:register` FIRST, before calling either use case, is load-bearing
here, not just a defensive duplicate.

**Handler order:** (1) `_require_authorized` (RBAC) -- (2)
`ProvisionStaffIdentity.execute(...)` (identity module: invite email +
`users`/`user_credentials` rows) -- (3) `RegisterStaff.execute(...,
user_id=<from step 2>)` (staff module, UNCHANGED, `staff_members` row).
Two separate business-module use cases, called from this platform-layer
router (never from each other -- backend/AGENTS.md's "business modules
never import each other directly").

**`operational_role='professional'` is NOT supported by this request shape
yet, flagged not silently broken:** `RegisterStaffRequest` has no
`professional_id` field (task's own scope: `site_id, name, operational_role,
email` only), and `users.professional_id IS NOT NULL` is a hard DB
constraint when `role='professional'` -- `ProvisionStaffIdentity` validates
this up front and raises a clean `ValidationError` (422) rather than letting
a raw `IntegrityError` leak through, but registering a `professional` staff
member via THIS route is genuinely not possible until a future revision
adds that field."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from app.composition_root import build_authorize_action, build_provision_staff_identity, build_register_staff
from app.modules.staff.domain.staff_member import OperationalRole
from app.platform.inbound.api.access_control.dependencies import get_db_conn, get_http_client, get_tenant_context
from app.shared_kernel.tenant_context import TenantContext

router = APIRouter(prefix="/staff", tags=["staff"])

# Mirrors `RegisterStaff`'s own private `_ACTION` module constant (staff
# module's `register_staff.py`) -- duplicated here, not imported (private),
# same convention `scheduling.py`'s router-level action constants use. MUST
# stay in sync with that use case's `_ACTION` value.
_REGISTER_ACTION = "staff:register"


class RegisterStaffRequest(BaseModel):
    site_id: str
    name: str
    operational_role: OperationalRole
    email: str


class RegisterStaffResponse(BaseModel):
    staff_member_id: str
    user_id: str
    email: str
    operational_role: str


async def _require_authorized(conn: AsyncConnection, ctx: TenantContext, *, action: str) -> None:
    """Explicit, router-level RBAC check -- see module docstring for why
    this is load-bearing here (not just a defensive duplicate of
    `RegisterStaff`'s own internal check)."""
    await build_authorize_action(conn).execute(ctx, action=action)


@router.post("/register", response_model=RegisterStaffResponse, status_code=201)
async def register(
    payload: RegisterStaffRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    conn: AsyncConnection = Depends(get_db_conn),
    http_client=Depends(get_http_client),
) -> RegisterStaffResponse:
    await _require_authorized(conn, ctx, action=_REGISTER_ACTION)

    identity_use_case = build_provision_staff_identity(conn, http_client=http_client, restore_role=ctx.role)
    account = await identity_use_case.execute(
        ctx.tenant_id,
        site_id=payload.site_id,
        email=payload.email,
        role=payload.operational_role.value,
        actor_id=ctx.actor_id,
    )

    register_staff = build_register_staff(conn)
    staff = await register_staff.execute(
        ctx,
        site_id=payload.site_id,
        name=payload.name,
        operational_role=payload.operational_role,
        user_id=account.id,
    )

    return RegisterStaffResponse(
        staff_member_id=staff.id,
        user_id=account.id,
        email=account.email,
        operational_role=staff.operational_role.value,
    )
