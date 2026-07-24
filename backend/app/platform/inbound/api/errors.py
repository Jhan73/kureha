"""Central error-taxonomy envelope + FastAPI exception handler (design.md
§21, ADR-23, tasks.md task 10.3). This is the "unica frontera de
traduccion" §21.2 requires: every domain/infra exception this codebase
raises -- and anything not otherwise mapped, including FastAPI's own
`RequestValidationError`/`HTTPException` -- passes through
`register_exception_handlers(app)` and comes back as the SAME structured
envelope shape:

    {"error_code", "category", "user_message", "retryable", "correlation_id"}

`user_message` is always a CURATED string keyed by `error_code`, never
`str(exception)` -- so no response path can accidentally leak a stack
trace, an exception class name, raw DB error text, or a secret (§21.2:
"user_message curado, no derivado del error interno"). The real
exception/stack only ever reaches server-side logs (stdlib `logging`, same
convention `audit_safety.py` established), tagged with the SAME
`correlation_id` the client receives, so support/ops can correlate a report
back to the real cause without exposing it.

**Resolution strategy, deliberately MRO-based, not per-exact-class:**
`_MAPPINGS` is keyed by exception CLASS, but `_resolve_mapping` walks
`type(exc).__mro__` to find the closest registered ancestor -- so
registering `shared_kernel.errors.NotFoundError`/`NotAuthorizedError`/
`ValidationError`/`ConflictError` ONCE here covers every module's own
subclass (`AppointmentNotFoundError`, `StaffMemberNotFoundError`,
`TenantNotFoundError`, ...) automatically, with no per-module registration
needed -- while still letting a MORE SPECIFIC subclass (e.g.
`ActionNotPermittedError`, `LlmBudgetExceededError`) override the generic
mapping with its own `error_code`/message/status when one is registered,
since Python's MRO always lists the subclass before its ancestor.

**Only 4 of design.md §21.1's 6 categories have real exception types to map
today** (`auth`, `validation`, `rate-limited`, plus the unmapped-exception
fallback under a `internal` category §21.1 does not explicitly name but
§21.2 requires: "una excepcion no mapeada cae a un `internal_error`/`500`
generico"). `calendar-sync-degraded` is communicated as a success-path
status, never raised as an exception (design.md §7.2: "no bloqueante...
aviso adjunto al resultado exitoso"), so it never reaches this handler by
construction. `hitl-pending`/`clinical-scope-refused` belong to the
LangGraph/HITL/scope-guardrail flows (tasks.md Phase 11/12/13, not built
yet) -- flagged here, not silently invented: whoever builds those phases
registers their exception types into `_MAPPINGS` the same way, rather than
building a second, competing translation layer."""

import logging
import uuid
from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.modules.calendar.domain.errors import OAuthStateMismatchError
from app.modules.governance.rbac.application.use_cases.authorize_action import ActionNotPermittedError
from app.modules.identity.domain.errors import (
    InactiveUserError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    RefreshReuseDetectedError,
    UnmappedIdentityError,
)
from app.platform.inbound.api.rate_limit.errors import LlmBudgetExceededError, RateLimitExceededError
from app.shared_kernel.errors import ConflictError, NotAuthorizedError, NotFoundError, ValidationError

logger = logging.getLogger(__name__)

_GENERIC_INTERNAL_MESSAGE = "Ocurrio un error, intenta mas tarde."


@dataclass(frozen=True, slots=True)
class ErrorEnvelope:
    """§21's exact wire shape."""

    error_code: str
    category: str
    user_message: str
    retryable: bool
    correlation_id: str

    def to_dict(self) -> dict:
        return {
            "error_code": self.error_code,
            "category": self.category,
            "user_message": self.user_message,
            "retryable": self.retryable,
            "correlation_id": self.correlation_id,
        }


@dataclass(frozen=True, slots=True)
class _ErrorMapping:
    http_status: int
    error_code: str
    category: str
    user_message: str
    retryable: bool = False


_INTERNAL_ERROR_MAPPING = _ErrorMapping(
    http_status=500,
    error_code="internal_error",
    category="internal",
    user_message=_GENERIC_INTERNAL_MESSAGE,
    retryable=False,
)

# Order does not matter for lookup (MRO-walk based, see module docstring) --
# grouped by §21.1 category for readability.
_MAPPINGS: dict[type[BaseException], _ErrorMapping] = {
    # auth
    NotAuthorizedError: _ErrorMapping(403, "auth_forbidden", "auth", "No tienes permiso para realizar esta accion."),
    ActionNotPermittedError: _ErrorMapping(
        403, "auth_forbidden", "auth", "No tienes permiso para realizar esta accion."
    ),
    InvalidCredentialsError: _ErrorMapping(401, "auth_required", "auth", "Credenciales invalidas."),
    UnmappedIdentityError: _ErrorMapping(401, "auth_required", "auth", "Credenciales invalidas."),
    InactiveUserError: _ErrorMapping(403, "auth_forbidden", "auth", "Tu cuenta esta inactiva."),
    InvalidRefreshTokenError: _ErrorMapping(
        401, "auth_required", "auth", "Tu sesion expiro, inicia sesion nuevamente."
    ),
    RefreshReuseDetectedError: _ErrorMapping(
        401, "auth_required", "auth", "Tu sesion expiro, inicia sesion nuevamente."
    ),
    # validation (NotFoundError/ConflictError also live under this category
    # per §21.1's note that `error_code` may be finer-grained than
    # `category` -- see module docstring)
    ValidationError: _ErrorMapping(422, "validation_error", "validation", "La solicitud no es valida."),
    OAuthStateMismatchError: _ErrorMapping(
        400,
        "oauth_state_mismatch",
        "validation",
        "No pudimos verificar la solicitud de conexion con Google Calendar, intenta nuevamente.",
    ),
    NotFoundError: _ErrorMapping(404, "not_found", "validation", "El recurso solicitado no existe."),
    ConflictError: _ErrorMapping(409, "conflict", "validation", "La solicitud entra en conflicto con el estado actual."),
    # rate-limited
    RateLimitExceededError: _ErrorMapping(
        429, "rate_limited", "rate-limited", "Demasiadas solicitudes, intenta mas tarde.", retryable=True
    ),
    LlmBudgetExceededError: _ErrorMapping(
        429,
        "llm_budget_exceeded",
        "rate-limited",
        "Se alcanzo el limite diario de uso del asistente.",
        retryable=False,
    ),
}


def register_exception_handlers(app: FastAPI) -> None:
    """Registers the single translation boundary on `app` -- overrides
    FastAPI's own default `RequestValidationError`/`HTTPException` handlers
    (which otherwise return their own, differently-shaped JSON body) so
    EVERY error surface funnels through the same envelope, plus a
    catch-all for any other `Exception`."""
    app.add_exception_handler(RequestValidationError, _handle_request_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(Exception, _handle_exception)


def _new_correlation_id() -> str:
    return f"req_{uuid.uuid4().hex}"


def _respond(mapping: _ErrorMapping, *, correlation_id: str | None = None) -> JSONResponse:
    envelope = ErrorEnvelope(
        error_code=mapping.error_code,
        category=mapping.category,
        user_message=mapping.user_message,
        retryable=mapping.retryable,
        correlation_id=correlation_id or _new_correlation_id(),
    )
    return JSONResponse(envelope.to_dict(), status_code=mapping.http_status)


async def _handle_exception(request: Request, exc: Exception) -> JSONResponse:
    mapping = _resolve_mapping(exc)
    correlation_id = _new_correlation_id()
    if mapping is None:
        # ADR-23: the real exception/stack is server-side-only -- never in
        # the response body, always tagged with the SAME correlation_id
        # the client receives so it can be found in these logs.
        logger.exception("Unhandled exception (correlation_id=%s)", correlation_id)
    return _respond(mapping if mapping is not None else _INTERNAL_ERROR_MAPPING, correlation_id=correlation_id)


def _resolve_mapping(exc: BaseException) -> _ErrorMapping | None:
    for cls in type(exc).__mro__:
        mapping = _MAPPINGS.get(cls)
        if mapping is not None:
            return mapping
    return None


async def _handle_request_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # §21.2: field-level detail is allowed ("fecha en el pasado"), the raw
    # pydantic error shape/internal type info is not -- curate a short,
    # field-path-only message instead of exposing `exc.errors()` verbatim.
    fields = ", ".join(".".join(str(part) for part in error["loc"]) for error in exc.errors()) or "body"
    mapping = _ErrorMapping(
        422, "validation_error", "validation", f"Solicitud invalida: revisa los campos ({fields})."
    )
    return _respond(mapping)


async def _handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    mapping = _HTTP_STATUS_FALLBACKS.get(exc.status_code, _INTERNAL_ERROR_MAPPING)
    return _respond(mapping)


_HTTP_STATUS_FALLBACKS: dict[int, _ErrorMapping] = {
    401: _ErrorMapping(401, "auth_required", "auth", "Debes iniciar sesion para continuar."),
    403: _ErrorMapping(403, "auth_forbidden", "auth", "No tienes permiso para realizar esta accion."),
    404: _ErrorMapping(404, "not_found", "validation", "El recurso solicitado no existe."),
    405: _ErrorMapping(405, "validation_error", "validation", "Metodo no permitido para esta ruta."),
    429: _ErrorMapping(429, "rate_limited", "rate-limited", "Demasiadas solicitudes, intenta mas tarde.", True),
}
