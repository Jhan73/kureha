import logging
import uuid
from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.modules.calendar.domain.errors import OAuthStateMismatchError
from app.modules.governance.consent.domain.errors import ConsentNotCurrentError
from app.modules.governance.rbac.application.use_cases.authorize_action import ActionNotPermittedError
from app.modules.identity.domain.errors import (
    InactiveUserError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    RefreshReuseDetectedError,
    UnmappedIdentityError,
)
from app.platform.inbound.api.access_control.operator_identity import OperatorCredentialError
from app.platform.inbound.api.rate_limit.errors import LlmBudgetExceededError, RateLimitExceededError
from app.platform.inbound.graph.streaming.response_guard_stream import ResponseGuardStreamRefusal
from app.shared_kernel.errors import ConflictError, NotAuthorizedError, NotFoundError, ValidationError

logger = logging.getLogger(__name__)

_GENERIC_INTERNAL_MESSAGE = "Ocurrio un error, intenta mas tarde."


@dataclass(frozen=True, slots=True)
class ErrorEnvelope:
    """Wire error payload."""

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


@dataclass(frozen=True, slots=True)
class ResolvedError:
    """Envelope plus HTTP status. SSE callers ignore http_status (stream is already 200)."""

    envelope: ErrorEnvelope
    http_status: int


_INTERNAL_ERROR_MAPPING = _ErrorMapping(
    http_status=500,
    error_code="internal_error",
    category="internal",
    user_message=_GENERIC_INTERNAL_MESSAGE,
    retryable=False,
)

# MRO lookup; grouped by category for readability.
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
    # separate from the tenant RBAC plane -- same generic message (anti-enumeration).
    OperatorCredentialError: _ErrorMapping(401, "auth_required", "auth", "Credenciales invalidas."),
    # validation (error_code may be finer-grained than category)
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
    # clinical-scope-refused (chat refusal is the response, often via SSE error)
    ResponseGuardStreamRefusal: _ErrorMapping(
        200,
        "clinical_scope_refused",
        "clinical-scope-refused",
        "Solo puedo ayudarte con temas administrativos; derivo tu consulta clinica a un profesional.",
        retryable=False,
    ),
    # consent-required: own category; English user_message is intentional
    ConsentNotCurrentError: _ErrorMapping(
        403,
        "consent_required",
        "consent-required",
        "You must accept the informed consent before continuing.",
        retryable=False,
    ),
}


def register_exception_handlers(app: FastAPI) -> None:
    """Register the shared error-envelope handlers on `app`."""
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


def resolve_error(exc: BaseException) -> ResolvedError:
    """Map any exception to the shared error envelope (also used by SSE `/chat/stream`)."""
    mapping = _resolve_mapping(exc)
    correlation_id = _new_correlation_id()
    if mapping is None:
        # Never leak stack/exception text to the client; correlate via logs.
        logger.exception("Unhandled exception (correlation_id=%s)", correlation_id)
        mapping = _INTERNAL_ERROR_MAPPING
    envelope = ErrorEnvelope(
        error_code=mapping.error_code,
        category=mapping.category,
        user_message=mapping.user_message,
        retryable=mapping.retryable,
        correlation_id=correlation_id,
    )
    return ResolvedError(envelope=envelope, http_status=mapping.http_status)


async def _handle_exception(request: Request, exc: Exception) -> JSONResponse:
    resolved = resolve_error(exc)
    return JSONResponse(resolved.envelope.to_dict(), status_code=resolved.http_status)


def _resolve_mapping(exc: BaseException) -> _ErrorMapping | None:
    for cls in type(exc).__mro__:
        mapping = _MAPPINGS.get(cls)
        if mapping is not None:
            return mapping
    return None


async def _handle_request_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Field paths only — do not expose raw pydantic error shapes.
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
