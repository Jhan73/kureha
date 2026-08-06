from app.shared_kernel.errors import NotFoundError, ValidationError


class CalendarCredentialNotFoundError(NotFoundError):
    """No active calendar_credentials row for (tenant_id, patient_id)."""


class OAuthStateMismatchError(ValidationError):
    """OAuth state mismatch (anti-CSRF); reject before exchanging code. Maps to 400."""


class CalendarOAuthExchangeError(ValidationError):
    """Google /token rejected the authorization code (stale/reused/wrong redirect)."""
