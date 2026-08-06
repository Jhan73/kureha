from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from app.composition_root import build_authorize_action, build_provision_staff_identity, build_register_staff
from app.modules.staff.domain.staff_member import OperationalRole
from app.platform.inbound.api.access_control.dependencies import get_db_conn, get_http_client, get_tenant_context
from app.shared_kernel.tenant_context import TenantContext

router = APIRouter(prefix="/staff", tags=["staff"])

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
