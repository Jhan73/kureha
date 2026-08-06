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
    model = build_chat_model("fast", settings=_settings(llm_fast_model="claude-haiku-9000"))

    assert model.model == "claude-haiku-9000"


def test_build_chat_model_defaults_to_the_process_wide_settings_singleton() -> None:
    model = build_chat_model("fast")

    assert model.model  # constructed without raising, using the real Settings singleton
