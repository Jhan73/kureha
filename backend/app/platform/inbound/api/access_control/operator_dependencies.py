from fastapi import Depends, Header, Request

from app.platform.inbound.api.access_control.operator_identity import (
    OperatorCredentialVerifierPort,
    OperatorIdentity,
)


def get_operator_credential_verifier(request: Request) -> OperatorCredentialVerifierPort:
    """The process-wide verifier built in `main.py`'s lifespan, same pattern as `get_http_client`."""
    return request.app.state.operator_credential_verifier


def require_operator(
    x_kureha_ops_key: str | None = Header(default=None, alias="X-Kureha-Ops-Key"),
    verifier: OperatorCredentialVerifierPort = Depends(get_operator_credential_verifier),
) -> OperatorIdentity:
    """Route/router dependency for the `/ops/*` plane; raises OperatorCredentialError on any denial."""
    return verifier.verify(x_kureha_ops_key)
