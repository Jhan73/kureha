import httpx
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel

from app.composition_root import (
    build_bootstrap_tenant,
    build_invite_existing_user,
    build_ops_bootstrap_rate_limiter,
    open_elevated_connection,
    open_runtime_connection,
)
from app.modules.governance.audit.adapters.outbound.postgres.audit_log import PostgresAuditLog
from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.modules.identity.domain.errors import CredentialInvitationFailedError
from app.modules.tenancy.domain.tenant_bootstrap import BootstrapTenantCommand
from app.platform.inbound.api.access_control.dependencies import get_http_client
from app.platform.inbound.api.access_control.operator_identity import (
    OperatorCredentialError,
    OperatorCredentialVerifierPort,
    OperatorIdentity,
)
from app.platform.inbound.api.access_control.operator_dependencies import get_operator_credential_verifier
from app.platform.inbound.api.audit_safety import record_audit_best_effort
from app.platform.inbound.api.rate_limit.errors import RateLimitExceededError
from app.platform.inbound.api.system_tenant import SYSTEM_TENANT_ID

_OPS_BOOTSTRAP_RATE_LIMIT_DIMENSION = "ops_bootstrap"
_OPS_BOOTSTRAP_RATE_LIMIT_WINDOW_SECONDS = 3600
_OPS_BOOTSTRAP_RATE_LIMIT_MAX_ATTEMPTS = 10


async def _require_operator(
    x_kureha_ops_key: str | None = Header(default=None, alias="X-Kureha-Ops-Key"),
    verifier: OperatorCredentialVerifierPort = Depends(get_operator_credential_verifier),
) -> OperatorIdentity:
    """Router-level guard: verifies `X-Kureha-Ops-Key`, auditing every denial
    against the system tenant (there is no real tenant to attribute a
    credential failure to at this point)."""
    try:
        return verifier.verify(x_kureha_ops_key)
    except OperatorCredentialError:
        async with open_elevated_connection() as conn:
            await record_audit_best_effort(
                PostgresAuditLog(conn),
                AuditEntry(
                    tenant_id=SYSTEM_TENANT_ID,
                    actor_type=AuditActorType.SYSTEM,
                    action=AuditAction.OPS_CREDENTIAL_DENIED,
                    object_type="ops_credential",
                ),
            )
        raise


router = APIRouter(prefix="/ops", tags=["ops"], dependencies=[Depends(_require_operator)])


class BootstrapTenantRequest(BaseModel):
    name: str
    admin_email: str
    tenant_id: str | None = None
    site_name: str | None = None


class TenantBootstrapResponse(BaseModel):
    tenant_id: str
    site_id: str
    admin_user_id: str
    admin_email: str
    credential_status: str


class AdminInviteRequest(BaseModel):
    site_id: str
    admin_user_id: str
    admin_email: str


class AdminInviteResponse(BaseModel):
    tenant_id: str
    admin_user_id: str
    admin_email: str
    credential_status: str


async def _check_ops_bootstrap_rate_limit(operator_key_id: str) -> bool:
    async with open_elevated_connection() as conn:
        return await build_ops_bootstrap_rate_limiter(conn).check(
            dimension=_OPS_BOOTSTRAP_RATE_LIMIT_DIMENSION,
            subject=operator_key_id,
            window_seconds=_OPS_BOOTSTRAP_RATE_LIMIT_WINDOW_SECONDS,
            limit=_OPS_BOOTSTRAP_RATE_LIMIT_MAX_ATTEMPTS,
            tenant_id=None,
        )


async def _invite_admin(
    *, tenant_id: str, user_id: str, site_id: str, email: str, http_client: httpx.AsyncClient
) -> str:
    """Runs `InviteExistingUser` post-commit on an elevated (bypass) connection --
    this is pre-auth, same precedent as `/auth/login`/`/auth/refresh`. Returns
    `credential_status`; an invite failure is reported, never raised as a 5xx."""
    async with open_elevated_connection() as conn:
        use_case = build_invite_existing_user(conn, http_client=http_client)
        try:
            await use_case.execute(tenant_id, user_id=user_id, site_id=site_id, email=email)
        except CredentialInvitationFailedError:
            return "invite_failed"
    return "invited"


@router.post("/tenants/bootstrap", status_code=201, response_model=TenantBootstrapResponse)
async def bootstrap_tenant(
    payload: BootstrapTenantRequest,
    operator: OperatorIdentity = Depends(_require_operator),
    http_client: httpx.AsyncClient = Depends(get_http_client),
) -> TenantBootstrapResponse:
    if not await _check_ops_bootstrap_rate_limit(operator.key_id):
        raise RateLimitExceededError()

    command = BootstrapTenantCommand(
        name=payload.name,
        admin_email=payload.admin_email,
        tenant_id=payload.tenant_id,
        site_name=payload.site_name,
    )

    async with open_runtime_connection() as conn:
        use_case = build_bootstrap_tenant(conn)
        result = await use_case.execute(command, operator_key_id=operator.key_id)

    credential_status = await _invite_admin(
        tenant_id=result.tenant_id,
        user_id=result.admin_user_id,
        site_id=result.site_id,
        email=result.admin_email,
        http_client=http_client,
    )

    return TenantBootstrapResponse(
        tenant_id=result.tenant_id,
        site_id=result.site_id,
        admin_user_id=result.admin_user_id,
        admin_email=result.admin_email,
        credential_status=credential_status,
    )


@router.post("/tenants/{tenant_id}/admin-invite", response_model=AdminInviteResponse)
async def retry_admin_invite(
    tenant_id: str,
    payload: AdminInviteRequest,
    operator: OperatorIdentity = Depends(_require_operator),
    http_client: httpx.AsyncClient = Depends(get_http_client),
) -> AdminInviteResponse:
    """Idempotent retry of the post-commit invite step; never touches the
    provisioning tables `bootstrap_tenant` already committed."""
    credential_status = await _invite_admin(
        tenant_id=tenant_id,
        user_id=payload.admin_user_id,
        site_id=payload.site_id,
        email=payload.admin_email,
        http_client=http_client,
    )

    return AdminInviteResponse(
        tenant_id=tenant_id,
        admin_user_id=payload.admin_user_id,
        admin_email=payload.admin_email,
        credential_status=credential_status,
    )
