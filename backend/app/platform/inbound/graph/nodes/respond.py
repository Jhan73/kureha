"""`respond` node (design.md §8.2/§8.3/§8.11.2, tasks.md task 11.5): the
graph's universal exit node -- every terminal edge ends `-> respond ->
END`.

**Pass-through first, compose only as a fallback -- `confirmation_gate.py`'s
own (batch 2) docstring already documents this exact contract: "respond can
be written once to mean 'pass through response_text if a node upstream
already set it, otherwise compose one from outcome/audit_ref'".**
`confirmation_gate` (needed/decline), `direct_respond`, `escalate_human`,
and `deny_action` all set `response_text` themselves before reaching this
node -- `respond` must NEVER overwrite that. Only the OPERATIONAL path
(`rbac_gate -ok-> confirmation_gate (not_required/affirmed) -> route_by_risk
-> [hitl_approval ->] persist_and_audit -> [calendar_sync ->] response_guard
-> respond`) reaches this node with `response_text` still `None` -- see
`response_guard.py`'s own docstring for why THAT path's guard pass on an
unset value is intentional, not a gap.

**Composed (fallback) text is template-based, from structured `outcome`/
`proposed_action.summary`/`calendar_sync_status` fields -- never a fresh
LLM call.** Nothing in this batch's scope wires a "compose a friendly final
message" LLM seam (design.md §8.10 does not name one for `respond`'s main
text either, only for its SUGGESTION generation, see below) -- keeping this
deterministic also means it structurally cannot introduce a NEW
clinical-scope-leak vector `response_guard` never validated (see
`response_guard.py`'s docstring for the other half of this reasoning).

**Suggestions (design.md §8.11.2) -- justified ONLY in the cases design.md
+ this task's own instructions name explicitly:** a successful
schedule/reschedule/cancel outcome, an `unknown` intent, or a
`greeting`/`capability_query` intent (design.md §8.11.2's own bullet list
includes this last one even though tasks.md's summarized wording only
repeats the first two -- design.md is the authoritative source, followed
here rather than the paraphrase). Anything else (error/escalation/denial
responses, which by construction already have `response_text` set and
return early above) gets `suggestions=None`, never an empty list -- design.md
§8.11.2: "no obligatorias... `suggestions` queda `None`".

**The RBAC-safety filter is enforced HERE, in plain code -- never
delegated to `SuggestionGeneratorPort`.** design.md §8.11.2: "Tony nunca
sugiere una accion que el usuario no tiene permiso de ejecutar" is a hard
security invariant, not a language-generation concern (this module's own
task instructions are explicit on this point) -- any `SuggestionCandidate`
whose `.action` is set but absent from `state.allowed_actions` is dropped
unconditionally, regardless of what the (untrusted, seam-generated) port
returned. A candidate with `action=None` (a purely orientational
suggestion, no concrete RBAC-gated action named) is never filtered -- there
is nothing to check. Truncated to 3 AFTER filtering (design.md: "el nodo
respond trunca la lista a 3 items si la generacion produce mas").

**CRITICAL checkpoint-cleanup invariant (found during PR 11's post-batch-3
verify pass, not in the original task text -- `KurehaState` is a plain
`TypedDict` with no `Annotated[..., reducer]` on any field, so LangGraph's
default `LastValue` channel NEVER clears a key a node's return dict simply
omits; the checkpointed value persists across turns by construction, the
exact same mechanism `confirmation_gate.py`'s own docstring already warns
about for ITS branches).** `respond` is the ONE node every single path in
design.md §8.3 passes through immediately before `END` -- which makes it
the only place that can reliably close this out for the whole graph.
Empirically confirmed reachable: without this, `persist_and_audit` (or any
other terminal node) leaves `proposed_action` sitting in the checkpoint
forever after a turn concludes, so `route_from_start`'s `proposed_action is
not None` check (design.md §8.2) incorrectly sends the NEXT, entirely
unrelated turn straight to `confirmation_gate` instead of `triage` --
silently breaking every conversation past its first completed action.
**The only turn that must NOT be cleared is `confirmation_gate`'s own
`"needed"` exit** (turn N, prompt just asked, `route_from_start` MUST see
`proposed_action` on the next turn to jump back into `confirmation_gate`
for the reply) -- every other terminal state (`not_required`/`affirmed`
outcomes that already executed or got HITL/RBAC/scope-denied, `decline`
which already self-clears, `direct_respond`'s conversational path which
never had a `proposed_action` to begin with) must leave the checkpoint
clean. `state.get("confirmation") == "needed"` is therefore the single
condition distinguishing "preserve" from "clear".

**Only `proposed_action` needs clearing -- `confirmation` itself is left
alone, deliberately.** Nothing downstream keys off a STALE `confirmation`
value the way `route_from_start` keys off `proposed_action is not None`:
`route_from_start`'s own condition never reads `confirmation` at all, and
`confirmation_gate`'s incoming-checkpoint read only ever tests for the
exact string `"needed"` -- a leftover `"affirmed"`/`"not_required"`/`None`
from 1+ turns ago is indistinguishable from "anything else" to that check,
so it is harmless to leave in place. Forcing `confirmation` to `None` here
would instead DESTROY the caller-visible signal of what actually happened
THIS turn (`chat.py`'s endpoint, or any future caller, reasonably wants to
know whether the just-completed turn was `not_required`/`affirmed`/etc.) --
confirmed by this file's own test: `test_low_risk_web_form_schedule_routes_
end_to_end_to_respond` asserts the graph's returned `confirmation ==
"not_required"` for the very turn that produced it."""

from app.platform.inbound.graph.ports.suggestion_generator import SuggestionContext, SuggestionGeneratorPort
from app.platform.inbound.graph.state import KurehaState

_MAX_SUGGESTIONS = 3
_SUGGESTIONS_HEADER = "¿También te puedo ayudar con?"
_GENERIC_SUCCESS_TEXT = "Listo, la acción se completó con éxito."
_GENERIC_FALLBACK_TEXT = "Tu solicitud fue procesada."

_OPERATIONAL_INTENTS = frozenset({"schedule", "reschedule", "cancel"})
_LIGHT_INTENTS = frozenset({"greeting", "capability_query"})


def _compose_response_text(state: KurehaState) -> str:
    outcome = state.get("outcome")
    if outcome is None or not outcome.success:
        return _GENERIC_FALLBACK_TEXT

    proposed_action = state.get("proposed_action")
    base = f"Listo, {proposed_action.summary}" if proposed_action is not None and proposed_action.summary else _GENERIC_SUCCESS_TEXT

    if state.get("calendar_sync_status") == "failed":
        base += " No pudimos sincronizar tu Google Calendar, pero la cita quedó registrada."

    return base


def _suggestions_justified(state: KurehaState) -> bool:
    intent = state.get("intent")
    if intent in _LIGHT_INTENTS or intent == "unknown":
        return True
    if intent in _OPERATIONAL_INTENTS:
        outcome = state.get("outcome")
        return outcome is not None and outcome.success
    return False


def _format_suggestions(response_text: str, suggestions: list[str]) -> str:
    bullet_list = "\n".join(f"- {text}" for text in suggestions)
    return f"{response_text}\n\n{_SUGGESTIONS_HEADER}\n{bullet_list}"


def make_respond_node(suggestion_generator: SuggestionGeneratorPort):
    async def respond(state: KurehaState) -> dict:
        response_text = state.get("response_text")
        if not response_text:
            response_text = _compose_response_text(state)

        suggestions: list[str] | None = None
        if _suggestions_justified(state):
            ctx = state["request_ctx"].to_tenant_context()
            outcome = state.get("outcome")
            allowed_actions = state.get("allowed_actions") or []
            candidates = await suggestion_generator.generate(
                ctx,
                context=SuggestionContext(
                    intent=state.get("intent"),
                    allowed_actions=list(allowed_actions),
                    outcome_success=outcome.success if outcome is not None else None,
                ),
            )
            allowed = set(allowed_actions)
            safe_texts = [c.text for c in candidates if c.action is None or c.action in allowed]
            suggestions = safe_texts[:_MAX_SUGGESTIONS] or None

        if suggestions:
            response_text = _format_suggestions(response_text, suggestions)

        result: dict = {"response_text": response_text, "suggestions": suggestions}
        if state.get("confirmation") == "needed":
            # Preserve explicitly (not merely omit) -- matches
            # confirmation_gate.py's own established convention of always
            # setting proposed_action on every branch, never relying on an
            # omitted key's checkpoint-carryover as the mechanism.
            result["proposed_action"] = state.get("proposed_action")
        else:
            # See this module's docstring: every exit EXCEPT confirmation_gate's
            # own "needed" prompt must leave the checkpoint clean, or the next,
            # unrelated turn gets silently misrouted back into confirmation_gate.
            # `confirmation` itself is intentionally left untouched (see docstring).
            result["proposed_action"] = None
        return result

    return respond
