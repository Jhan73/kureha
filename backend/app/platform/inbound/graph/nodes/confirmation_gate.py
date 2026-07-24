"""`confirmation_gate` node (design.md §8.9, tasks.md task 11.3): the
lightweight, non-`interrupt()` conversational confirmation gate every
conversational-channel mutation must pass before `route_by_risk`. NOT the
same mechanism as `hitl_approval` (tasks.md task 11.4) -- design.md §8.4
point 3 is explicit the two are orthogonal and neither replaces the other.

**Where the prompt/cancellation text lives -- `response_text`, a deliberate
choice for batch 3's `respond`/`response_guard` (tasks.md task 11.5, not yet
built) to consume.** `KurehaState` has exactly one field meant to carry
outbound conversational text (`response_text` -- design.md §8.1's own field
list has no separate "draft" field). design.md §8.3's edge for the `needed`
branch is `confirmation_gate (needed) -> response_guard -> respond -> END`,
i.e. this node's prompt IS the turn's entire response (the graph never
reaches `persist_and_audit` this turn) -- the same shape `direct_respond`
will use for its own conversational replies (tasks.md task 12.5), so
`respond` can be written once to mean "pass through `response_text` if a
node upstream already set it, otherwise compose one from `outcome`/
`audit_ref`" rather than every terminal node needing a bespoke field.
`response_guard` (task 11.5) validates `response_text` the same way
regardless of which node populated it.

**Turn N vs turn N+1 -- disambiguated by reading the INCOMING checkpointed
`confirmation` value, combined with `AffirmationClassifierPort`'s three-way
verdict.** `confirmation_gate` is reached via TWO different edges (design.md
§8.3): `rbac_gate -> confirmation_gate` (turn N, `proposed_action` just built
by a specialist THIS turn from `channel_message`) and `route_from_start ->
confirmation_gate` (turn N+1, `proposed_action` loaded from the checkpoint,
`channel_message` is the user's NEW reply). Design.md's own note ("el campo
confirmation es None al inicio de cada turno -- se recomputa") describes
what this node itself must always freshly compute ON ITS WAY OUT (never
blindly carry a stale value forward) -- it does NOT forbid reading the
INCOMING value as an input signal. Since this node explicitly sets
`confirmation` on every single exit branch (the critical invariant
documented below), the checkpoint entering turn N+1 genuinely holds turn
N's last written value (`"needed"`) -- exactly the signal needed to tell the
two turns apart: `was_awaiting_reply = state.get("confirmation") ==
"needed"`, captured at the top of the node BEFORE this invocation
computes/overwrites anything.

Per design.md §8.9 Caso B vs Caso C, the SAME "not an explicit yes" outcome
must resolve DIFFERENTLY depending on turn (turn N: `"needed"`, ask; turn
N+1: decline, give up -- §8.9's Caso C explicitly lists "cambio de topico"
as a decline trigger, not a re-ask) -- a plain boolean `affirmed` cannot
express that asymmetry, so `AffirmationClassifierPort` returns a THREE-way
verdict (see that port's own docstring for the full rationale): `"unclear"`
means "not a reply to any yes/no question" -- which is only actually true
on turn N (`was_awaiting_reply is False`). When `was_awaiting_reply is True`
and the classifier still returns `"unclear"`, the message WAS a reply to an
already-asked prompt and failed to affirm it -- treated identically to an
explicit `"declined"` verdict (same branch, same checkpoint cleanup),
otherwise an ambiguous turn-N+1 reply would loop forever re-asking instead
of declining.

**The critical invariant (design.md §8.9, stated explicitly and repeated
across multiple paragraphs): every exit branch returns `proposed_action`
EXPLICITLY -- `None` on decline, the original object (not merely left out
of the dict) on every other branch.** LangGraph's checkpointer does NOT
clear a `TypedDict` key a node's return dict simply omits -- the previous
checkpointed value silently persists. Omitting `proposed_action` from the
`not_required`/`needed`/`affirmed` branches would happen to "work" today
(the value is already correct in the checkpoint) but would be a landmine
for any future edit to this node -- so every branch sets it explicitly,
matching the invariant design.md states rather than relying on an accident
of the current checkpoint value."""

from app.platform.inbound.graph.ports.affirmation_classifier import AffirmationClassifierPort
from app.platform.inbound.graph.state import KurehaState, ProposedAction

_DECLINE_RESPONSE_TEXT = "Entendido, no realicé la acción. ¿Te ayudo con algo más?"


def _confirmation_prompt(proposed_action: ProposedAction) -> str:
    """design.md §8.9 Caso B point 1's literal example shape ("Voy a
    reservar una cita con la Dra. X el martes 10:00. ¿Confirmas?"). Built
    from `proposed_action.summary` -- the specialist planner
    (`scheduling_agent`/`reminders_agent`/`staff_agent`) already renders the
    human-readable action/entity/key-detail text into `summary` from its own
    structured plan (date/time/professional/patient, whatever it had);
    re-deriving that formatting here from the generic `payload` dict would
    duplicate per-action-type logic each planner already owns. `summary` IS
    the "prompt built from the structured proposed_action" design.md asks
    for."""
    base = proposed_action.summary or proposed_action.action
    return f"{base} ¿Confirmas?"


def make_confirmation_gate_node(affirmation_classifier: AffirmationClassifierPort):
    async def confirmation_gate(state: KurehaState) -> dict:
        # Captured BEFORE this invocation computes/overwrites anything --
        # see this module's docstring ("Turn N vs turn N+1") for why this
        # incoming-checkpoint read is the disambiguation signal, not a
        # violation of "confirmation is recomputed every turn".
        was_awaiting_reply = state.get("confirmation") == "needed"

        proposed_action = state.get("proposed_action")
        if proposed_action is None:
            # Structurally unreachable via design.md §8.3's edges -- both
            # entry edges into this node (rbac_gate and route_from_start)
            # only fire when a proposed_action exists -- guarded defensively
            # rather than raising, matching rbac_gate's own precedent.
            return {"confirmation": "not_required", "proposed_action": None}

        if state["channel"] == "web_form" or not proposed_action.is_mutating:
            # Caso A (design.md §8.9): deterministic web_form or a read-only
            # action never needs conversational confirmation.
            return {"confirmation": "not_required", "proposed_action": proposed_action}

        ctx = state["request_ctx"].to_tenant_context()
        verdict = await affirmation_classifier.classify(
            ctx, state["channel_message"], pending_action_summary=proposed_action.summary
        )

        if verdict.decision == "affirmed":
            # Caso C, affirmation branch: hand off to route_by_risk (task
            # 11.6) unchanged -- proposed_action must survive intact.
            return {"confirmation": "affirmed", "proposed_action": proposed_action}

        if verdict.decision == "declined":
            # Caso C, decline branch -- THE critical checkpoint-cleanup
            # invariant this module's docstring is about.
            return {
                "confirmation": None,
                "proposed_action": None,
                "response_text": _DECLINE_RESPONSE_TEXT,
            }

        # "unclear" AND we were awaiting a reply (turn N+1, Caso C) -- this
        # is an ambiguous/topic-changing reply to an ALREADY-ASKED prompt,
        # not a fresh request. design.md §8.9 lists "cambio de topico"
        # explicitly as a decline trigger -- treat identically to
        # "declined" so the checkpoint gets cleaned instead of looping
        # forever re-asking the same question.
        if was_awaiting_reply:
            return {
                "confirmation": None,
                "proposed_action": None,
                "response_text": _DECLINE_RESPONSE_TEXT,
            }

        # "unclear" and NOT awaiting a reply -- Caso B: first time this
        # action is proposed, nothing to affirm/decline yet. Ask, and keep
        # proposed_action pending.
        return {
            "confirmation": "needed",
            "proposed_action": proposed_action,
            "response_text": _confirmation_prompt(proposed_action),
        }

    return confirmation_gate
