"""Auth router (tasks.md task 10.1): `POST /auth/login`, `POST
/auth/refresh`, `POST /auth/logout`, `POST /auth/password-reset/request`,
`POST /auth/password-reset/confirm` (the last two added this session,
staff-invite / password-reset batch).

`password-reset/request`/`password-reset/confirm` are pre-auth, same as
`login`/`refresh` -- see `app/main.py`'s `_ACCESS_CONTROL_EXEMPT_PATH_PREFIXES`/
`_AUTH_RATE_LIMIT_PROTECTED_PREFIXES` (both now include `/auth/password-reset`
as a prefix, covering both new routes with one entry). `confirm` is the SAME
completion endpoint for BOTH a newly-invited staff member's first "set your
password" screen (`ProvisionStaffIdentity`, `routers/staff.py`) and an
existing user's "forgot password" flow -- see `AuthPort.complete_password_reset`'s
own docstring for why these are deliberately one endpoint, not two.

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
header/subdomain claim instead.

**Account-dimension (`auth_account`) login rate limit, closing
`auth_rate_limit_middleware.py`'s own deferred-gap docstring** (design.md
§19 layer 3, `rate_counters.dimension`): the IP dimension alone lets an
attacker distributing password guesses for ONE account across many IPs go
completely unthrottled. `login` below checks `auth_account` (subject
`f"{tenant_id}:{email}"`, genuinely tenant-scoped -- `find_by_email` is
itself tenant-scoped, so the same email under two different tenants must
not share a counter) BEFORE calling `use_case.with_password(...)`: fail
fast, avoiding both a wasted Supabase round trip and leaking that adapter's
own timing during an attack. The counter increments on EVERY attempt
regardless of outcome -- same semantics as the existing IP dimension.

**Deviation from the "reuse `Login`'s own connection, no new connection"
plan, flagged not silently applied -- confirmed empirically THIS session
(a genuinely failing test, not a hypothetical) that the literal plan is
incorrect:** the account-limit check runs on its OWN, SEPARATE
`open_elevated_connection()` (`_check_and_audit_account_rate_limit` below),
never the same connection `build_login`/`use_case.with_password(...)` uses.
Sharing one connection/transaction was tried first and empirically broke
the whole feature: `with_password` raises `InvalidCredentialsError` for
every wrong-password attempt (the overwhelmingly common case this limiter
exists to catch), and that exception propagates out of the SAME `async
with open_elevated_connection()` block the rate-limit increment had
JUST run inside -- rolling the increment back together with it. A wrong
password would therefore never actually accumulate against the limit,
silently defeating brute-force protection while every test using ONLY
correct-or-absent passwords would still appear to pass. Isolating the
check into its own connection, committed before `Login` ever runs, is the
same pattern `app/main.py`'s `_ElevatedRateCounterStore` already uses for
the IP dimension (a fresh connection per counter operation, decoupled from
whatever the request itself does afterward) and `calendar_oauth.py`'s
`_audit_csrf_attempt` uses for its audit write, for the identical
underlying reason (see that function's own docstring). `RateLimitExceededError`
is raised only AFTER that connection's block has already exited/committed,
never from inside it -- consistent with the same "audit write must survive
the request's own outcome" principle.

**Second, narrower instance of the same hazard, found by a fresh-review
pass and fixed in the same session:** `_check_and_audit_account_rate_limit`
originally ran the counter increment AND the audit write on one shared
connection -- which reintroduces the identical rollback risk one level
down. See that function's own docstring for the concrete repro (a bogus,
never-validated `tenant_id` makes the audit INSERT violate `audit_logs`'s
real tenant FK -- `rate_counters.tenant_id` has none -- and committing a
Postgres transaction already marked aborted by that caught exception
silently discards every write made in it, including the counter increment).
Fixed by giving the audit write its OWN, separately-committed connection,
opened only after the counter connection has already committed."""

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

# design.md §19 layer 3 / tasks.md task 10.2's forward pointer: the
# `auth_account` dimension, mirroring `app/main.py`'s
# `_AUTH_RATE_LIMIT_WINDOW_SECONDS`/`_AUTH_RATE_LIMIT_MAX_ATTEMPTS` naming
# for the IP dimension. 5 attempts per 5 minutes, deliberately tighter than
# the IP dimension's 10/60s -- a single account being guessed at is a
# stronger signal than a single IP making auth traffic.
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
    # `tenant_id` here is a DEVIATION from this batch's own initial plan
    # (`{recovery_token, new_password}` only), flagged not silently applied:
    # `UserDirectoryPort.find_by_auth_subject`/`find_by_email` -- which
    # `CompletePasswordReset` needs to resolve the Supabase identity back to
    # a `users` row -- are BOTH tenant-scoped by construction (this
    # codebase's own multi-tenant architecture, no exception exists
    # anywhere else for these lookups), and this module's OWN docstring
    # already establishes that `tenant_id` is caller-supplied on every
    # pre-auth route (`LoginRequest.tenant_id`, same "no subdomain/host
    # tenant-resolution strategy exists yet" rationale) -- there is no OTHER
    # way to resolve the correct tenant here without inventing a new
    # mechanism out of scope for this batch.
    tenant_id: str
    recovery_token: str
    new_password: str


async def _check_and_audit_account_rate_limit(*, tenant_id: str, email: str) -> bool:
    """Two SEPARATE `open_elevated_connection()` blocks, deliberately not
    one -- fresh-review finding (this session): sharing a single connection
    between the counter increment and the audit write reintroduces a
    narrower version of the same rollback hazard this module's own docstring
    already documents for `Login`. `LoginRequest.tenant_id` is caller-
    supplied and never validated against a real `tenants` row before this
    runs (this module's own docstring), and `audit_logs.tenant_id` is
    `NOT NULL REFERENCES tenants(id)` while `rate_counters.tenant_id` has no
    FK at all -- so a bogus `tenant_id` lets the counter increment succeed
    while the audit INSERT genuinely violates the FK. `record_audit_best_effort`
    catches that exception, but Postgres has already marked the transaction
    aborted; committing an aborted transaction silently discards EVERY write
    made in it, including the counter increment that ran first -- reproduced
    empirically, not theorized. Committing the counter increment in its own
    connection BEFORE the audit write ever opens its own means the audit
    path can fail/no-op without touching the counter's already-durable
    state, mirroring `app/main.py`'s `_ElevatedRateCounterStore`/
    `_ElevatedAuditLog` (two classes, each a fresh connection per call, for
    the identical reason on the IP dimension).

    Returns whether the attempt is ALLOWED; when it is not, the
    `auth.rate_limited` audit entry is best-effort -- a failure there can
    never block the deny decision from taking effect."""
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
    # Checked (and, on denial, audited) BEFORE `Login` ever runs: fail
    # fast, avoiding both a wasted Supabase round trip and leaking that
    # adapter's own timing during an attack -- see this module's own
    # docstring for why this runs on a separate connection from `Login`'s.
    if not await _check_and_audit_account_rate_limit(tenant_id=payload.tenant_id, email=payload.email):
        raise RateLimitExceededError()

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


@router.post("/password-reset/request", status_code=204)
async def request_password_reset(payload: PasswordResetRequest, http_client=Depends(get_http_client)) -> None:
    """Pre-auth, like `login`/`refresh` (exempt from `AccessControlMiddleware`,
    protected by the SAME IP-dimension rate limiter -- see `app/main.py`'s
    `_ACCESS_CONTROL_EXEMPT_PATH_PREFIXES`/`_AUTH_RATE_LIMIT_PROTECTED_PREFIXES`).
    Always 204, regardless of whether `payload.email` resolves to anything --
    `RequestPasswordReset`/`AuthPort.start_password_reset`'s own
    anti-enumeration contract, see those modules' docstrings. Deliberately
    NO account-dimension rate limiter here (unlike `login` above) -- this
    route has no "guessing a password against a known account" shape to
    protect against; IP-dimension throttling alone is the correct match for
    a request/enumeration-probing risk, per this batch's own scope."""
    use_case = build_request_password_reset(http_client)
    await use_case.execute(payload.email)


@router.post("/password-reset/confirm", response_model=TokenResponse)
async def confirm_password_reset(
    payload: PasswordResetConfirmRequest, http_client=Depends(get_http_client)
) -> TokenResponse:
    """Pre-auth, same reasoning as `request_password_reset` above. Mints and
    returns a fresh access+refresh pair on success (judgment call, see
    `CompletePasswordReset`'s own module docstring for the UX rationale) --
    the SAME completion endpoint for both a newly-invited staff member's
    first "set your password" screen and an existing user's "forgot
    password" flow."""
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
