"""LLM tier factory (tasks.md task 12.7, design.md §8.10): the ONE place
`LlmTier -> concrete ChatAnthropic instance` resolution happens. Every real
LLM-backed adapter in Phase 12 (this batch: `AnthropicScopePolicy`,
`AnthropicIntentClassifier`, `AnthropicAffirmationClassifier`; batches 2/3:
the scheduling/reminder/staff planners, direct response, suggestion
generator) MUST go through `build_chat_model()` -- never construct
`ChatAnthropic` inline, never hardcode a model id string anywhere else
(this task's own literal wording).

**Provider/models decided, not this module's call to revisit** (confirmed
by the user): Anthropic via `langchain-anthropic`'s `ChatAnthropic`, two
tiers per design.md §8.10's table --

- `"fast"` -> `settings.llm_fast_model` (default `claude-haiku-4-5`):
  every node design.md §8.10 marks "Rápido/chico".
- `"reasoner"` -> `settings.llm_reasoner_model` (default `claude-sonnet-5`):
  `scheduling_agent`/`staff_agent`.

Both the API key and the two tier model ids are read from `Settings`
(`app/config.py`) at CALL time (never cached/memoized at import time), so
they are genuinely overridable via env var per tasks.md task 12.7's own
requirement -- see `tests/platform/inbound/graph/adapters/test_llm.py` for
the test proving the mapping is live, not a bare literal.

**Constructing `ChatAnthropic` never itself calls the Anthropic API** (only
an actual `.ainvoke()`/`.with_structured_output(...).ainvoke()` call does)
-- confirmed via `langchain-anthropic`'s own pydantic model fields
(`inspect`-verified, not guessed): `model` (aliased `model_name`) and
`anthropic_api_key` (aliased `api_key`, a `pydantic.SecretStr`, empty
string accepted at construction time). This is what lets every adapter in
this batch be constructed safely in a test/CI environment with no real API
key configured -- only a genuine integration smoke test (gated behind
`settings.anthropic_api_key`, matching `test_calendar_oauth_router.py`'s
`skipif(not settings.aws_endpoint_url, ...)` precedent) would need a real
key."""

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
