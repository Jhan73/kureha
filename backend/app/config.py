from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "local"

    database_url: str = (
        "postgresql+asyncpg://app_user:dev_only_password@localhost:5432/kureha_dev"
    )

    # app_runtime: non-superuser, non-BYPASSRLS — use this to validate RLS.
    # app_user above is bootstrap superuser and bypasses RLS.
    runtime_database_url: str = (
        "postgresql+asyncpg://app_runtime:dev_only_password@localhost:5432/kureha_dev"
    )

    # None/"" -> real AWS; "http://localhost:4566" -> LocalStack.
    aws_endpoint_url: str | None = None
    aws_default_region: str = "us-east-1"

    # Supabase Auth (GoTrue) only — Kureha DB stays separate.
    # Current Dashboard keys: publishable + secret (not legacy anon/service_role JWTs).
    supabase_url: str | None = None
    supabase_publishable_key: str | None = None
    # Elevated secret for invite_user; never expose to the frontend.
    supabase_secret_key: str | None = None

    # Access-JWT secret; production must override (dev default is fake).
    identity_access_token_secret: str = "dev_only_access_token_secret_change_me"
    identity_access_token_ttl_minutes: int = 10
    identity_refresh_token_ttl_days: int = 30
    identity_refresh_grace_period_seconds: int = 30

    calendar_google_client_id: str = "dev_only_google_client_id_change_me"
    calendar_google_client_secret: str = "dev_only_google_client_secret_change_me"
    calendar_oauth_redirect_uri: str = "http://localhost:8000/calendar/oauth/callback"
    # Separate from identity_access_token_secret so rotating one does not invalidate the other.
    calendar_oauth_state_secret: str = "dev_only_calendar_oauth_state_secret_change_me"

    # Model ids only via platform/.../llm.build_chat_model — never hardcode in nodes.
    anthropic_api_key: str | None = None
    llm_fast_model: str = "claude-haiku-4-5"
    llm_reasoner_model: str = "claude-sonnet-5"

    # Per-instance token-bucket: burst 5, refill 0.5/s (tunable via env).
    chat_rate_limit_capacity: int = 5
    chat_rate_limit_refill_per_second: float = 0.5

    # Comma-separated origins; no wildcard (credentialed CORS).
    cors_allowed_origins: str = "http://localhost:3000"

    # Canonical frontend origin for Supabase invite/password-reset redirect_to.
    frontend_base_url: str = "http://localhost:3000"

    # Comma-separated `key_id:sha256_hex` pairs for the operator credential plane
    # (X-Kureha-Ops-Key). Empty -> StaticOperatorCredentialVerifier denies everything.
    ops_bootstrap_credentials: str = ""
    # Kill-switch: the /ops router only registers when this is True.
    ops_bootstrap_enabled: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
