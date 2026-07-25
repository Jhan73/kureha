"""Application settings.

Single source of truth for environment configuration, read once at process
start via `pydantic-settings`. Adapters (boto3 clients, the SQLAlchemy async
engine, etc.) receive values from here rather than reading `os.environ`
directly — see design.md §22.4/§22.6 for the local-vs-production rationale
(only `.env.local` changes; adapter code never branches on environment).
"""

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

    # Restricted, non-superuser, non-BYPASSRLS role (design.md §4.2: "sin
    # BYPASSRLS") -- created by infra/postgres/init/02_app_runtime_role.sql.
    # RLS policies are only meaningfully enforced against this role; `app_user`
    # above is the Postgres bootstrap superuser and unconditionally bypasses
    # RLS, so it must never be used to validate RLS behavior (tasks.md 2.9).
    runtime_database_url: str = (
        "postgresql+asyncpg://app_runtime:dev_only_password@localhost:5432/kureha_dev"
    )

    # boto3 clients read this and fall back to real AWS when it's empty
    # (design.md §22.6): None/"" -> AWS real, "http://localhost:4566" -> LocalStack.
    aws_endpoint_url: str | None = None
    aws_default_region: str = "us-east-1"

    # Identity module (design.md §17, tasks.md Phase 4). Adapters take these
    # via constructor injection (composition root, task 10.2) rather than
    # reading `settings` directly -- see e.g. `SupabaseAuthAdapter`'s
    # constructor -- so this section is scaffolding for that future wiring,
    # not yet consumed anywhere in this PR.
    #
    # Supabase Auth (GoTrue) project, standalone (ADR-14) -- Kureha's own DB
    # never migrates to Supabase, only auth flows call this API.
    supabase_url: str | None = None
    supabase_anon_key: str | None = None

    # Kureha's own access-JWT signing secret (ADR-15) -- the dev default is
    # intentionally obviously-fake ("dev_only_..."), matching the convention
    # already used for `database_url`'s dev password; production MUST
    # override via a real Secrets Manager-backed value (design.md §22.6).
    identity_access_token_secret: str = "dev_only_access_token_secret_change_me"
    identity_access_token_ttl_minutes: int = 10
    identity_refresh_token_ttl_days: int = 30
    identity_refresh_grace_period_seconds: int = 30

    # Calendar module (design.md §7.3, tasks.md task 10.1). `GoogleCalendarAdapter`
    # takes these via constructor injection (composition root), same convention as
    # `identity_access_token_secret` above -- this section is scaffolding for that
    # wiring, consumed for the first time by task 10.1's OAuth2 authorize/callback
    # routers.
    calendar_google_client_id: str = "dev_only_google_client_id_change_me"
    calendar_google_client_secret: str = "dev_only_google_client_secret_change_me"
    calendar_oauth_redirect_uri: str = "http://localhost:8000/calendar/oauth/callback"
    # HMAC secret for `GoogleCalendarAdapter.generate_oauth_state`/`verify_oauth_state`
    # (design.md §7.3's anti-CSRF `state`) -- deliberately a SEPARATE secret from
    # `identity_access_token_secret`: the two protect different things (a signed
    # session token vs. a one-shot CSRF nonce) and rotating one must not silently
    # invalidate the other.
    calendar_oauth_state_secret: str = "dev_only_calendar_oauth_state_secret_change_me"

    # LLM provider (design.md §8.10, tasks.md task 12.7). `None` until
    # configured -- same convention as `supabase_anon_key` above -- so a
    # local/CI run with no key set can still import/construct every
    # `ChatAnthropic`-backed adapter (constructing the client does not
    # itself call the API); only an actual `.ainvoke()` needs a real key.
    # Tier -> model id is resolved ONLY by
    # `platform/inbound/graph/adapters/llm.py`'s `build_chat_model()` -- no
    # node/adapter file may hardcode a model id string (tasks.md task 12.7's
    # own explicit requirement).
    anthropic_api_key: str | None = None
    llm_fast_model: str = "claude-haiku-4-5"
    llm_reasoner_model: str = "claude-sonnet-5"

    # Patient chat rate limiting (design.md §19 layer 3, tasks.md task
    # 12.1's rate-limiter/budget wiring): per-instance token-bucket
    # cadence gate, keyed `tenant+patient` (spec `platform-hardening`,
    # "Rate Limiting on Patient Chat"). design.md names the MECHANISM
    # (token-bucket, per-instance) but not concrete capacity/refill
    # numbers -- these two are an MVP judgment call, tunable per
    # environment via env vars rather than hardcoded in
    # `ChatRateLimiter`/`TokenBucketRegistry` themselves (this codebase's
    # own "never hardcoded" convention, task 12.7's own wording, applied
    # here too even though design.md itself left the exact values open).
    # Burst of 5 messages, refilling at 1 every 2s sustained.
    chat_rate_limit_capacity: int = 5
    chat_rate_limit_refill_per_second: float = 0.5


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
