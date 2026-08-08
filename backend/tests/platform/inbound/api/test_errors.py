from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.modules.calendar.domain.errors import OAuthStateMismatchError
from app.modules.governance.rbac.application.use_cases.authorize_action import ActionNotPermittedError
from app.modules.identity.domain.errors import InvalidCredentialsError, UnmappedIdentityError
from app.modules.scheduling.domain.errors import AppointmentNotFoundError, SlotUnavailableError
from app.platform.inbound.api.access_control.operator_identity import OperatorCredentialError
from app.platform.inbound.api.errors import register_exception_handlers, resolve_error
from app.platform.inbound.api.rate_limit.errors import LlmBudgetExceededError, RateLimitExceededError
from app.shared_kernel.errors import ValidationError


class _Body(BaseModel):
    name: str


def _build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom/not-authorized")
    def _not_authorized():
        raise ActionNotPermittedError("appointment:create")

    @app.get("/boom/invalid-credentials")
    def _invalid_credentials():
        raise InvalidCredentialsError()

    @app.get("/boom/unmapped-identity")
    def _unmapped_identity():
        raise UnmappedIdentityError()

    @app.get("/boom/not-found")
    def _not_found():
        raise AppointmentNotFoundError("appt-1")

    @app.get("/boom/conflict")
    def _conflict():
        raise SlotUnavailableError("slot-1")

    @app.get("/boom/validation")
    def _validation():
        raise ValidationError("bad input")

    @app.get("/boom/oauth-state-mismatch")
    def _oauth_state_mismatch():
        raise OAuthStateMismatchError()

    @app.get("/boom/operator-credential")
    def _operator_credential():
        raise OperatorCredentialError("bad ops credential")

    @app.get("/boom/rate-limited")
    def _rate_limited():
        raise RateLimitExceededError("too many requests")

    @app.get("/boom/llm-budget")
    def _llm_budget():
        raise LlmBudgetExceededError("daily budget exceeded")

    @app.get("/boom/unmapped")
    def _unmapped():
        raise RuntimeError("some internal database connection string leaked here")

    @app.post("/boom/body")
    def _body(body: _Body):
        return {"name": body.name}

    return app


def _client() -> TestClient:
    return TestClient(_build_app(), raise_server_exceptions=False)


_ENVELOPE_KEYS = {"error_code", "category", "user_message", "retryable", "correlation_id"}


def test_action_not_permitted_maps_to_auth_forbidden_403() -> None:
    response = _client().get("/boom/not-authorized")

    assert response.status_code == 403
    body = response.json()
    assert set(body.keys()) == _ENVELOPE_KEYS
    assert body["category"] == "auth"
    assert body["error_code"] == "auth_forbidden"
    assert body["retryable"] is False


def test_invalid_credentials_maps_to_auth_required_401() -> None:
    response = _client().get("/boom/invalid-credentials")

    assert response.status_code == 401
    assert response.json()["category"] == "auth"
    assert response.json()["error_code"] == "auth_required"


def test_unmapped_identity_also_maps_to_auth_required_401() -> None:
    response = _client().get("/boom/unmapped-identity")

    assert response.status_code == 401
    assert response.json()["category"] == "auth"


def test_operator_credential_error_maps_to_auth_required_401_not_auth_forbidden() -> None:
    response = _client().get("/boom/operator-credential")

    assert response.status_code == 401
    body = response.json()
    assert body["category"] == "auth"
    assert body["error_code"] == "auth_required"


def test_not_found_error_maps_to_validation_category_404() -> None:
    response = _client().get("/boom/not-found")

    assert response.status_code == 404
    body = response.json()
    assert body["category"] == "validation"
    assert body["error_code"] == "not_found"


def test_conflict_error_maps_to_validation_category_409() -> None:
    response = _client().get("/boom/conflict")

    assert response.status_code == 409
    body = response.json()
    assert body["category"] == "validation"
    assert body["error_code"] == "conflict"


def test_validation_error_maps_to_422() -> None:
    response = _client().get("/boom/validation")

    assert response.status_code == 422
    body = response.json()
    assert body["category"] == "validation"
    assert body["error_code"] == "validation_error"


def test_oauth_state_mismatch_maps_to_validation_category_400() -> None:
    response = _client().get("/boom/oauth-state-mismatch")

    assert response.status_code == 400
    body = response.json()
    assert body["category"] == "validation"
    assert body["error_code"] == "oauth_state_mismatch"
    assert body["retryable"] is False


def test_rate_limit_exceeded_maps_to_429_and_is_retryable() -> None:
    response = _client().get("/boom/rate-limited")

    assert response.status_code == 429
    body = response.json()
    assert body["category"] == "rate-limited"
    assert body["error_code"] == "rate_limited"
    assert body["retryable"] is True


def test_llm_budget_exceeded_is_a_more_specific_rate_limit_and_not_retryable() -> None:
    response = _client().get("/boom/llm-budget")

    assert response.status_code == 429
    body = response.json()
    assert body["category"] == "rate-limited"
    assert body["error_code"] == "llm_budget_exceeded"
    assert body["retryable"] is False


def test_unmapped_exception_falls_back_to_generic_internal_error_500() -> None:
    response = _client().get("/boom/unmapped")

    assert response.status_code == 500
    body = response.json()
    assert set(body.keys()) == _ENVELOPE_KEYS
    assert body["error_code"] == "internal_error"
    assert body["category"] == "internal"
    assert body["retryable"] is False
    # invariant: never leak the raw exception message/stack.
    assert "database connection string" not in body["user_message"]
    assert "RuntimeError" not in body["user_message"]


def test_request_body_validation_error_maps_to_422_without_raw_pydantic_shape() -> None:
    response = _client().post("/boom/body", json={"name": 123, "extra": "x"})

    assert response.status_code == 422
    body = response.json()
    assert set(body.keys()) == _ENVELOPE_KEYS
    assert body["category"] == "validation"
    assert body["error_code"] == "validation_error"


def test_every_response_has_a_unique_correlation_id() -> None:
    client = _client()
    first = client.get("/boom/unmapped").json()["correlation_id"]
    second = client.get("/boom/unmapped").json()["correlation_id"]

    assert first != second
    assert first.startswith("req_")


def test_resolve_error_returns_the_same_envelope_shape_a_mapped_exception_maps_to() -> None:
    resolved = resolve_error(RateLimitExceededError("too many"))

    assert resolved.envelope.error_code == "rate_limited"
    assert resolved.envelope.category == "rate-limited"
    assert resolved.envelope.retryable is True
    assert resolved.envelope.correlation_id.startswith("req_")
    assert resolved.http_status == 429


def test_resolve_error_falls_back_to_internal_error_for_an_unmapped_exception() -> None:
    resolved = resolve_error(RuntimeError("boom"))

    assert resolved.envelope.error_code == "internal_error"
    assert resolved.envelope.category == "internal"
    assert resolved.http_status == 500
    assert "boom" not in resolved.envelope.user_message


def test_resolve_error_produces_a_fresh_correlation_id_each_call() -> None:
    first = resolve_error(RuntimeError("boom"))
    second = resolve_error(RuntimeError("boom"))

    assert first.envelope.correlation_id != second.envelope.correlation_id
