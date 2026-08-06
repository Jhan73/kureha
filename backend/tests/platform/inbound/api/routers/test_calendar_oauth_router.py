import urllib.parse

import httpx
import pytest

from app.config import settings
from app.main import app
from app.platform.inbound.api.access_control.dependencies import get_http_client
from tests.platform.inbound.api.routers.conftest import auth_headers, count_audit_rows, mint_access_token, seed_patient_actor

pytestmark = pytest.mark.skipif(
    not settings.aws_endpoint_url, reason="requires AWS_ENDPOINT_URL pointed at a running LocalStack (AesGcmVault KEK)"
)


def _authorize_url_state(authorize_url: str) -> str:
    query = urllib.parse.urlparse(authorize_url).query
    return urllib.parse.parse_qs(query)["state"][0]


def _fake_google_transport(*, refresh_token: str, email: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(
                200, json={"access_token": "google-access-token", "refresh_token": refresh_token, "scope": "calendar.events"}
            )
        assert request.url.path == "/oauth2/v3/userinfo"
        return httpx.Response(200, json={"email": email})

    return httpx.MockTransport(handler)


def test_calendar_oauth_connects_end_to_end_for_a_valid_state(client) -> None:
    patient = seed_patient_actor()
    token = mint_access_token(
        tenant_id=patient["tenant_id"], site_id=patient["site_id"], role="patient", user_id=patient["user_id"]
    )

    authorize_response = client.get("/calendar/oauth/authorize", headers=auth_headers(token))
    assert authorize_response.status_code == 200
    state = _authorize_url_state(authorize_response.json()["authorize_url"])

    app.dependency_overrides[get_http_client] = lambda: httpx.AsyncClient(
        transport=_fake_google_transport(refresh_token="google-refresh-token-1", email="patient1@example.com")
    )
    try:
        callback_response = client.get(
            f"/calendar/oauth/callback?code=auth-code-1&state={state}", headers=auth_headers(token)
        )
    finally:
        app.dependency_overrides.pop(get_http_client, None)

    assert callback_response.status_code == 200
    body = callback_response.json()
    assert body["status"] == "connected"
    assert body["credential_id"]


def test_calendar_oauth_callback_rejects_a_mismatched_state_and_audits_it(client) -> None:
    patient = seed_patient_actor()
    token = mint_access_token(
        tenant_id=patient["tenant_id"], site_id=patient["site_id"], role="patient", user_id=patient["user_id"]
    )

    authorize_response = client.get("/calendar/oauth/authorize", headers=auth_headers(token))
    assert authorize_response.status_code == 200

    callback_response = client.get(
        "/calendar/oauth/callback?code=auth-code-1&state=tampered-state-value", headers=auth_headers(token)
    )

    assert callback_response.status_code == 400
    body = callback_response.json()
    assert body["error_code"] == "oauth_state_mismatch"
    assert body["category"] == "validation"
    assert "correlation_id" in body

    assert count_audit_rows(patient["tenant_id"], "calendar.oauth_csrf_attempt") == 1


def test_calendar_oauth_callback_without_the_nonce_cookie_is_rejected(client) -> None:
    patient = seed_patient_actor()
    token = mint_access_token(
        tenant_id=patient["tenant_id"], site_id=patient["site_id"], role="patient", user_id=patient["user_id"]
    )

    # Simulates an attacker/direct callback hit with no prior `/authorize`
    # call on this client -- clear whatever nonce cookie an earlier test in
    # this module may have left in the shared client's cookie jar.
    client.cookies.clear()

    response = client.get("/calendar/oauth/callback?code=auth-code-1&state=anything", headers=auth_headers(token))

    assert response.status_code == 400
    assert response.json()["error_code"] == "oauth_state_mismatch"
