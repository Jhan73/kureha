from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from app.composition_root import (
    build_auth_account_rate_limiter,
    build_complete_password_reset,
    build_login,
    build_logout,
    build_refresh_token,
    build_request_password_reset,
    open_elevated_connection,
)
from app.modules.governance.audit.adapters.outbound.postgres.audit_log import PostgresAuditLog
from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.platform.inbound.api.access_control.dependencies import get_db_conn, get_http_client, get_tenant_context
from app.platform.inbound.api.audit_safety import record_audit_best_effort
from app.platform.inbound.api.rate_limit.errors import RateLimitExceededError
from app.shared_kernel.tenant_context import TenantContext

router = APIRouter(prefix="/auth", tags=["auth"])

_AUTH_ACCOUNT_RATE_LIMIT_DIMENSION = "auth_account"
_AUTH_ACCOUNT_RATE_LIMIT_WINDOW_SECONDS = 300
_AUTH_ACCOUNT_RATE_LIMIT_MAX_ATTEMPTS = 5


class LoginRequest(BaseModel):
    tenant_id: str
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    user_id: str
    role: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class PasswordResetRequest(BaseModel):
    tenant_id: str
    email: str


class PasswordResetConfirmRequest(BaseModel):
    tenant_id: str
    recovery_token: str
    new_password: str


async def _check_and_audit_account_rate_limit(*, tenant_id: str, email: str) -> bool:
    """Increment the account counter, then audit on a separate connection if denied."""
    subject = f"{tenant_id}:{email}"
    async with open_elevated_connection() as conn:
        allowed = await build_auth_account_rate_limiter(conn).check(
            dimension=_AUTH_ACCOUNT_RATE_LIMIT_DIMENSION,
            subject=subject,
            window_seconds=_AUTH_ACCOUNT_RATE_LIMIT_WINDOW_SECONDS,
            limit=_AUTH_ACCOUNT_RATE_LIMIT_MAX_ATTEMPTS,
            tenant_id=tenant_id,
        )
    if not allowed:
        async with open_elevated_connection() as audit_conn:
            await record_audit_best_effort(
                PostgresAuditLog(audit_conn),
                AuditEntry(
                    tenant_id=tenant_id,
                    actor_type=AuditActorType.SYSTEM,
                    action=AuditAction.AUTH_RATE_LIMITED,
                    object_type="auth_rate_limit",
                    payload={"subject": subject, "path": "/auth/login", "dimension": _AUTH_ACCOUNT_RATE_LIMIT_DIMENSION},
                ),
            )
    return allowed


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, http_client=Depends(get_http_client)) -> TokenResponse:
    if not await _check_and_audit_account_rate_limit(tenant_id=payload.tenant_id, email=payload.email):
        raise RateLimitExceededError()

    async with open_elevated_connection() as conn:
        use_case = build_login(conn, http_client=http_client)
        result = await use_case.with_password(payload.tenant_id, email=payload.email, password=payload.password)
    return TokenResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        user_id=result.user.id,
        role=result.user.role,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest) -> TokenResponse:
    async with open_elevated_connection() as conn:
        use_case = build_refresh_token(conn)
        result = await use_case.execute(refresh_token=payload.refresh_token)
    return TokenResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        user_id=result.user.id,
        role=result.user.role,
    )


@router.post("/logout", status_code=204)
async def logout(
    payload: LogoutRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    conn: AsyncConnection = Depends(get_db_conn),
) -> None:
    use_case = build_logout(conn)
    await use_case.execute(ctx, refresh_token=payload.refresh_token)


@router.post("/password-reset/request", status_code=204)
async def request_password_reset(payload: PasswordResetRequest, http_client=Depends(get_http_client)) -> None:
    use_case = build_request_password_reset(http_client)
    await use_case.execute(payload.email)


@router.post("/password-reset/confirm", response_model=TokenResponse)
async def confirm_password_reset(
    payload: PasswordResetConfirmRequest, http_client=Depends(get_http_client)
) -> TokenResponse:
    async with open_elevated_connection() as conn:
        use_case = build_complete_password_reset(conn, http_client=http_client)
        result = await use_case.execute(
            payload.tenant_id, recovery_token=payload.recovery_token, new_password=payload.new_password
        )
    return TokenResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        user_id=result.user.id,
        role=result.user.role,
    )
