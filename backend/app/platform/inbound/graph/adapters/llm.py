from typing import Literal

from langchain_anthropic import ChatAnthropic

from app.config import Settings
from app.config import settings as default_settings

LlmTier = Literal["fast", "reasoner"]


def build_chat_model(tier: LlmTier, *, settings: Settings | None = None) -> ChatAnthropic:
    """Constructs a `ChatAnthropic` for the given tier. `settings` defaults
    to the process-wide `app.config.settings` singleton every other adapter
    in this codebase reads from -- test callers may override it (see
    `test_llm.py`) to prove the tier->model mapping is genuinely read live,
    without needing to mutate process-wide env vars."""
    resolved = settings or default_settings
    model_id = resolved.llm_fast_model if tier == "fast" else resolved.llm_reasoner_model
    return ChatAnthropic(model=model_id, api_key=resolved.anthropic_api_key or "")
