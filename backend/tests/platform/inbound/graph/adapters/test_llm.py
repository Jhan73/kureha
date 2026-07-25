"""tasks.md task 12.7 (design.md §8.10): `build_chat_model()` is the ONE
place tier -> concrete Anthropic model id resolution happens. Every real
LLM-backed adapter in Phase 12 must go through this factory rather than
constructing `ChatAnthropic` inline or hardcoding a model id string (this
task's own explicit requirement) -- these tests prove the tier -> model
mapping is read live from `Settings` (so it is genuinely overridable via env
var), never a bare literal baked into this module."""

from app.config import Settings
from app.platform.inbound.graph.adapters.llm import build_chat_model


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "anthropic_api_key": "test-key",
        "llm_fast_model": "claude-haiku-4-5",
        "llm_reasoner_model": "claude-sonnet-5",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def test_fast_tier_resolves_to_the_configured_fast_model() -> None:
    model = build_chat_model("fast", settings=_settings())

    assert model.model == "claude-haiku-4-5"


def test_reasoner_tier_resolves_to_the_configured_reasoner_model() -> None:
    model = build_chat_model("reasoner", settings=_settings())

    assert model.model == "claude-sonnet-5"


def test_tier_resolution_reads_live_from_settings_not_hardcoded() -> None:
    """The literal defaults in `Settings` match design.md §8.10's decided
    models, but this factory must resolve them via `Settings` at call time
    -- proven by overriding the settings value and observing the resolved
    model change accordingly (a hardcoded string could never do this)."""
    model = build_chat_model("fast", settings=_settings(llm_fast_model="claude-haiku-9000"))

    assert model.model == "claude-haiku-9000"


def test_build_chat_model_defaults_to_the_process_wide_settings_singleton() -> None:
    """No `settings=` override -- the factory must fall back to
    `app.config.settings` (the same singleton every other adapter in this
    codebase reads from), not silently require every caller to pass one."""
    model = build_chat_model("fast")

    assert model.model  # constructed without raising, using the real Settings singleton
