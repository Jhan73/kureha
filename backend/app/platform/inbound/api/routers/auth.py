"""Auth router (tasks.md task 10.1): `POST /auth/login`, `POST
/auth/refresh`, `POST /auth/logout`.

`login`/`refresh` are pre-auth by definition -- listed in `app/main.py`'s
`exempt_path_prefixes` so `AccessControlMiddleware` never runs for them --
and each opens its OWN `composition_root.open_elevated_connection()` per
request (there is no `request.state.db_conn` yet; see `Login`/
`RefreshToken`'s own docstrings for why the elevated, pre-`app.*`-GUC
connection is the correct one here). Both are also listed in
`AuthRateLimitMiddleware`'s `protected_path_prefixes` (design.md §19 layer
3, tasks.md task 5.3) -- throttled by IP before this handler ever runs.

`logout` runs BEHIND `AccessControlMiddleware` (self-service, needs a
resolved actor to scope "revoke only YOUR OWN session" -- `Logout`'s own
docstring: "not RBAC-gated... contrast with `RevokeAllSessionsForUser`") and
uses the request's already-open, RLS-scoped `request.state.db_conn` like
every other authenticated route.

**`LoginRequest.tenant_id` is presented by the caller, not resolved from a
subdomain/host header** -- design.md does not specify a tenant-resolution
strategy for the web-form login route (only the `POST /chat/stream`
endpoint is spec'd, §11), and multi-tenant host-based routing is
infrastructure (ALB/Route53) this backend PR does not own. Flagged, not
silently invented: whoever builds the real frontend/gateway either resolves
`tenant_id` from the clinic's own subdomain and forwards it in the body (as
here), or a future revision of this route resolves it from a trusted
header/subdomain claim instead."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from app.composition_root import build_login, build_logout, build_refresh_token, open_elevated_connection
from app.platform.inbound.api.access_control.dependencies import get_db_conn, get_http_client, get_tenant_context
from app.shared_kernel.tenant_context import TenantContext

router = APIRouter(prefix="/auth", tags=["auth"])


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


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, http_client=Depends(get_http_client)) -> TokenResponse:
    async with open_elevated_connection() as conn:
        use_case = build_login(conn, http_client=http_client)
        # `.with_password` only -- `AccountLinkRequired`/federated login is
        # `.with_google`, out of this route's scope (no federated-login
        # request contract exists yet; flagged, not silently merged into
        # this endpoint's response shape).
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
