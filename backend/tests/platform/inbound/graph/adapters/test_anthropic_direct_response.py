"""tasks.md task 12.5 (PR 12 batch 2): `AnthropicDirectResponse`, the real
`DirectResponsePort` adapter `direct_respond` consumes (design.md §8.10/
§8.11.1/§8.11.3 -- Tony's identity/system prompt). Fast tier."""

from app.platform.inbound.graph.adapters.anthropic_direct_response import AnthropicDirectResponse
from app.shared_kernel.tenant_context import TenantContext

_CTX = TenantContext(tenant_id="tenant-1", role="patient")


class _FakeStructuredRunnable:
    def __init__(self, result_or_exc) -> None:
        self._result_or_exc = result_or_exc
        self.calls: list[list] = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        if isinstance(self._result_or_exc, BaseException):
            raise self._result_or_exc
        return self._result_or_exc


class _FakeChatModel:
    def __init__(self, result_or_exc) -> None:
        self._result_or_exc = result_or_exc
        self.runnable: _FakeStructuredRunnable | None = None

    def with_structured_output(self, schema, **kwargs):
        self.runnable = _FakeStructuredRunnable(self._result_or_exc)
        return self.runnable


class _TextResult:
    def __init__(self, text: str) -> None:
        self.text = text


async def test_respond_returns_the_models_generated_text() -> None:
    llm = _FakeChatModel(_TextResult("¡Hola! Soy Tony, ¿en qué te puedo ayudar?"))
    adapter = AnthropicDirectResponse(llm)

    plan = await adapter.respond(_CTX, intent="greeting", message="hola", allowed_actions=None)

    assert plan.text == "¡Hola! Soy Tony, ¿en qué te puedo ayudar?"


async def test_capability_query_sends_only_the_callers_allowed_actions() -> None:
    """design.md §8.11.1: "Tony nunca menciona acciones que el usuario no
    tiene permiso de ejecutar" -- the prompt must carry ONLY the caller's own
    `allowed_actions`, never the full action catalog."""
    llm = _FakeChatModel(_TextResult("Puedo ayudarte a agendar una cita."))
    adapter = AnthropicDirectResponse(llm)

    await adapter.respond(
        _CTX, intent="capability_query", message="que podes hacer?", allowed_actions=["appointment:create"]
    )

    assert llm.runnable is not None
    sent = " ".join(str(m.content) for m in llm.runnable.calls[0])
    assert "appointment:create" in sent
    assert "staff:register" not in sent
    assert "appointment:cancel" not in sent


async def test_capability_query_with_no_allowed_actions_never_invents_a_capability() -> None:
    llm = _FakeChatModel(_TextResult("Puedo orientarte administrativamente."))
    adapter = AnthropicDirectResponse(llm)

    await adapter.respond(_CTX, intent="capability_query", message="que podes hacer?", allowed_actions=None)

    assert llm.runnable is not None
    sent = " ".join(str(m.content) for m in llm.runnable.calls[0])
    for key in ("appointment:create", "staff:register", "shift:create"):
        assert key not in sent


async def test_message_reaches_the_model() -> None:
    llm = _FakeChatModel(_TextResult("¡Buen día!"))
    adapter = AnthropicDirectResponse(llm)

    await adapter.respond(_CTX, intent="small_talk", message="que lindo dia hace hoy", allowed_actions=None)

    assert llm.runnable is not None
    sent = llm.runnable.calls[0]
    assert any("que lindo dia hace hoy" in str(m.content) for m in sent)


async def test_respond_falls_back_to_a_canned_reply_on_an_llm_error() -> None:
    """Unlike the planners (no failure-routing edge exists), `direct_respond`
    is a purely conversational path with no side effect beyond a chat
    reply -- a safe canned fallback here is a reasonable, deliberate
    degrade-gracefully choice, matching `respond.py`'s own precedent of
    hardcoded Spanish fallback templates (`_GENERIC_FALLBACK_TEXT`)."""
    llm = _FakeChatModel(RuntimeError("boom"))
    adapter = AnthropicDirectResponse(llm)

    plan = await adapter.respond(_CTX, intent="greeting", message="hola", allowed_actions=None)

    assert plan.text
