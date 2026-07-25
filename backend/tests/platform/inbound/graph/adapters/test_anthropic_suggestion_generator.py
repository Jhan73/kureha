"""tasks.md task 12.6 (PR 12 batch 2): `AnthropicSuggestionGenerator`, the
real `SuggestionGeneratorPort` adapter `respond` consumes (design.md
§8.10/§8.11.2). Fast tier.

**RBAC-safety is NOT this adapter's job -- `respond.py`'s own docstring:
"the RBAC-safety filter is enforced HERE, in plain code -- never delegated
to `SuggestionGeneratorPort`". These tests only prove this adapter generates
candidates and degrades gracefully; the actual allowed-actions filter is
covered by `test_respond.py`, unchanged by this batch."""

import pytest

from app.platform.inbound.graph.adapters.anthropic_suggestion_generator import AnthropicSuggestionGenerator
from app.platform.inbound.graph.ports.suggestion_generator import SuggestionContext
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


class _Candidate:
    def __init__(self, text: str, action: str | None = None) -> None:
        self.text = text
        self.action = action


class _Suggestions:
    def __init__(self, suggestions: list[_Candidate]) -> None:
        self.suggestions = suggestions


async def test_generate_returns_candidates_from_the_model() -> None:
    llm = _FakeChatModel(
        _Suggestions(
            [
                _Candidate("¿Agregar un recordatorio para esta cita?", action="appointment:view"),
                _Candidate("¿Ver disponibilidad del mismo profesional la próxima semana?"),
            ]
        )
    )
    generator = AnthropicSuggestionGenerator(llm)

    result = await generator.generate(
        _CTX,
        context=SuggestionContext(
            intent="schedule",
            allowed_actions=["appointment:view"],
            outcome_success=True,
            proposed_action_summary="Agenda una cita el martes 10:00 con la Dra. Vega.",
        ),
    )

    assert [c.text for c in result] == [
        "¿Agregar un recordatorio para esta cita?",
        "¿Ver disponibilidad del mismo profesional la próxima semana?",
    ]
    assert result[0].action == "appointment:view"
    assert result[1].action is None


async def test_generate_sends_the_proposed_action_summary_and_outcome_to_the_model() -> None:
    """design.md §8.11.2's examples are contextual to the JUST-COMPLETED
    outcome -- the prompt must carry the real `proposed_action_summary`, not
    a generic one, or every suggestion degenerates into boilerplate."""
    llm = _FakeChatModel(_Suggestions([_Candidate("¿Notificar al profesional?")]))
    generator = AnthropicSuggestionGenerator(llm)

    await generator.generate(
        _CTX,
        context=SuggestionContext(
            intent="reschedule",
            allowed_actions=["appointment:reschedule"],
            outcome_success=True,
            proposed_action_summary="Reprograma la cita del jueves con el Dr. Ramos al viernes 3pm.",
        ),
    )

    assert llm.runnable is not None
    sent = " ".join(str(m.content) for m in llm.runnable.calls[0])
    assert "Reprograma la cita del jueves con el Dr. Ramos al viernes 3pm." in sent
    assert "reschedule" in sent


async def test_generate_sends_only_the_callers_allowed_actions() -> None:
    llm = _FakeChatModel(_Suggestions([]))
    generator = AnthropicSuggestionGenerator(llm)

    await generator.generate(
        _CTX,
        context=SuggestionContext(intent="unknown", allowed_actions=["appointment:create"], outcome_success=None),
    )

    assert llm.runnable is not None
    sent = " ".join(str(m.content) for m in llm.runnable.calls[0])
    assert "appointment:create" in sent
    assert "staff:register" not in sent


async def test_generate_returns_an_empty_list_on_an_llm_error() -> None:
    """`UnwiredSuggestionGenerator`'s own established contract: suggestions
    are explicitly optional (design.md §8.11.2: "no obligatorias") -- a
    generator failure must degrade to no suggestions, never fail the whole
    turn."""
    llm = _FakeChatModel(RuntimeError("boom"))
    generator = AnthropicSuggestionGenerator(llm)

    result = await generator.generate(
        _CTX, context=SuggestionContext(intent="schedule", allowed_actions=[], outcome_success=True)
    )

    assert result == []


@pytest.mark.parametrize("field", ["proposed_action_summary"])
async def test_generate_tolerates_a_missing_optional_context_field(field) -> None:
    llm = _FakeChatModel(_Suggestions([_Candidate("Puedo ayudarte a agendar, reprogramar o cancelar.")]))
    generator = AnthropicSuggestionGenerator(llm)

    result = await generator.generate(
        _CTX, context=SuggestionContext(intent="unknown", allowed_actions=[], outcome_success=None)
    )

    assert len(result) == 1
