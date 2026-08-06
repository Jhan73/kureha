import secrets

from fastapi import APIRouter, Cookie, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from app.composition_root import build_connect_patient_calendar, build_google_calendar_adapter, open_runtime_connection
from app.config import settings
from app.modules.calendar.adapters.outbound.calendar.google_calendar_adapter import GoogleCalendarAdapter
from app.modules.calendar.domain.connect_calendar_result import CalendarConnected, CalendarEmailMismatch
from app.modules.calendar.domain.errors import OAuthStateMismatchError
from app.modules.governance.audit.adapters.outbound.postgres.audit_log import PostgresAuditLog
from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.platform.inbound.api.access_control.dependencies import (
    get_db_conn,
    get_http_client,
    get_live_actor,
    get_tenant_context,
)
from app.platform.inbound.api.access_control.live_actor import LiveActor
from app.platform.inbound.api.access_control.session_context import set_session_context
from app.platform.inbound.api.audit_safety import record_audit_best_effort
from app.shared_kernel.tenant_context import TenantContext

router = APIRouter(prefix="/calendar/oauth", tags=["calendar"])

_NONCE_COOKIE = "kureha_calendar_oauth_nonce"
_NONCE_COOKIE_MAX_AGE_SECONDS = 600
_GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_SCOPE = "https://www.googleapis.com/auth/calendar.events"


class AuthorizeResponse(BaseModel):
    authorize_url: str


class ConnectResponse(BaseModel):
    status: str
    credential_id: str | None = None
    registered_email: str | None = None
    google_email: str | None = None


@router.get("/authorize", response_model=AuthorizeResponse)
async def authorize(response: Response, actor: LiveActor = Depends(get_live_actor)) -> AuthorizeResponse:
    nonce = secrets.token_urlsafe(24)
    state = GoogleCalendarAdapter.generate_oauth_state(
        user_id=actor.user_id, nonce=nonce, server_secret=settings.calendar_oauth_state_secret
    )
    response.set_cookie(
        _NONCE_COOKIE,
        nonce,
        max_age=_NONCE_COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    query = (
        f"client_id={settings.calendar_google_client_id}"
        f"&redirect_uri={settings.calendar_oauth_redirect_uri}"
        f"&response_type=code&access_type=offline&prompt=consent"
        f"&scope={_SCOPE}&state={state}"
    )
    return AuthorizeResponse(authorize_url=f"{_GOOGLE_AUTHORIZE_URL}?{query}")


@router.get("/callback", response_model=ConnectResponse)
async def callback(
    response: Response,
    code: str = Query(...),
    state: str = Query(...),
    calendar_oauth_nonce: str | None = Cookie(default=None, alias=_NONCE_COOKIE),
    actor: LiveActor = Depends(get_live_actor),
    ctx: TenantContext = Depends(get_tenant_context),
    conn: AsyncConnection = Depends(get_db_conn),
    http_client=Depends(get_http_client),
) -> ConnectResponse:
    response.delete_cookie(_NONCE_COOKIE)

    if calendar_oauth_nonce is None or not GoogleCalendarAdapter.verify_oauth_state(
        user_id=actor.user_id,
        nonce=calendar_oauth_nonce,
        server_secret=settings.calendar_oauth_state_secret,
        received_state=state,
    ):
        await _audit_csrf_attempt(actor)
        raise OAuthStateMismatchError()

    adapter = build_google_calendar_adapter(http_client)
    exchange = await adapter.exchange_authorization_code(code, redirect_uri=settings.calendar_oauth_redirect_uri)

    use_case = build_connect_patient_calendar(conn)
    result = await use_case.execute(
        ctx,
        patient_id=actor.patient_id,
        google_email=exchange.google_email,
        refresh_token=exchange.refresh_token,
        scope=exchange.scope,
    )

    if isinstance(result, CalendarConnected):
        return ConnectResponse(status="connected", credential_id=result.credential_id)
    assert isinstance(result, CalendarEmailMismatch)
    return ConnectResponse(status="email_mismatch", registered_email=result.registered_email, google_email=result.google_email)


async def _audit_csrf_attempt(actor: LiveActor) -> None:
    """Writes on a FRESH, independently-committed connection
    (`open_runtime_connection()`), never the route's own
    `request.state.db_conn` -- `AccessControlMiddleware._forward_with_session`
    rolls that connection back whenever the route raises (`commit =
    response.status_code < 500` only evaluates for a response `call_next`
    actually RETURNS; a raised `OAuthStateMismatchError` propagates past
    `call_next` entirely, so `commit` stays `False`). Writing the CSRF-attempt
    audit row on the shared connection would silently roll it back together
    with the deny -- exactly the failure mode `audit_safety.py`'s
    `record_audit_best_effort` exists to prevent at the middleware layer;
    this is the same fix applied one layer up, where a real Postgres
    connection is available instead of a fire-and-forget `AuditLogPort`."""
    async with open_runtime_connection() as audit_conn:
        await set_session_context(audit_conn, actor)
        await record_audit_best_effort(
            PostgresAuditLog(audit_conn),
            AuditEntry(
                tenant_id=actor.tenant_id,
                site_id=actor.site_id,
                actor_id=actor.user_id,
                actor_type=AuditActorType.USER,
                action=AuditAction.CALENDAR_OAUTH_CSRF_ATTEMPT,
                object_type="calendar_credential",
                object_id=actor.patient_id,
                reason="OAuth2 callback state did not match the nonce issued at /calendar/oauth/authorize",
            ),
        )
