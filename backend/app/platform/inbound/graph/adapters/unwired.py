"""`Unwired*` placeholders for every graph-local LLM-shaped seam port this
package's nodes depend on (`IntentClassifierPort`, `SchedulingPlannerPort`,
`ReminderPlannerPort`, `StaffPlannerPort`, `AffirmationClassifierPort`,
`DirectResponsePort`, `SuggestionGeneratorPort`).

**Why these exist, and why NOW (tasks.md task 11.6/11.7, batch 3):**
`build_graph()` (this same batch) must produce a genuinely COMPILED,
end-to-end-wireable graph -- task 11.7's chat endpoint has to construct one
for real, not just in a unit test. But no real LLM adapter for any of these
ports exists anywhere in this codebase yet (batch 1/2's own docstrings
flagged this repeatedly: "whoever eventually builds the real LLM adapters, a
later phase, not yet scheduled by name in tasks.md" -- still true, LLM
wiring is tasks.md Phase 12's job, not this one). Something has to satisfy
each port's constructor slot so the app can start and the graph can compile
-- these are that something, following the EXACT established precedent of
`UnwiredStaffStatusAdapter` (`modules/scheduling/adapters/outbound/
staff_status/unwired_adapter.py`) and `UnwiredAppointmentSnapshotAdapter`
(`modules/calendar/adapters/outbound/appointment_snapshot/unwired_adapter.py`):
duck-type the Protocol, raise `NotImplementedError` naming exactly which
future task must replace it.

Each one is deliberately a THIN, separate class (not one generic
`raise NotImplementedError` catch-all) so a future adapter swap-in is a
single, obvious diff -- matching the two precedents above, which are also
one class per port rather than a shared base."""

from app.platform.inbound.graph.ports.affirmation_classifier import AffirmationResult
from app.platform.inbound.graph.ports.direct_response import DirectResponsePlan
from app.platform.inbound.graph.ports.intent_classifier import IntentClassificationResult
from app.platform.inbound.graph.ports.reminder_planner import ReminderPlan
from app.platform.inbound.graph.ports.scheduling_planner import SchedulingPlan
from app.platform.inbound.graph.ports.staff_planner import StaffPlan
from app.platform.inbound.graph.ports.suggestion_generator import SuggestionCandidate


class UnwiredIntentClassifier:
    """Duck-types `IntentClassifierPort` -- wire a real LLM-backed adapter
    at a future LLM-wiring task (tasks.md Phase 12) before any real chat
    turn reaches `triage`."""

    async def classify(self, ctx, message: str) -> IntentClassificationResult:
        raise NotImplementedError(
            "UnwiredIntentClassifier is a placeholder -- wire a real IntentClassifierPort "
            "implementation (tasks.md Phase 12, LLM wiring) before a real chat turn reaches triage."
        )


class UnwiredSchedulingPlanner:
    """Duck-types `SchedulingPlannerPort`."""

    async def plan(self, ctx, *, intent: str, message: str) -> SchedulingPlan:
        raise NotImplementedError(
            "UnwiredSchedulingPlanner is a placeholder -- wire a real SchedulingPlannerPort "
            "implementation (tasks.md Phase 12, LLM wiring) before scheduling_agent runs for real."
        )


class UnwiredReminderPlanner:
    """Duck-types `ReminderPlannerPort`."""

    async def plan(self, ctx, *, message: str) -> ReminderPlan:
        raise NotImplementedError(
            "UnwiredReminderPlanner is a placeholder -- wire a real ReminderPlannerPort "
            "implementation (tasks.md Phase 12, LLM wiring) before reminders_agent runs for real."
        )


class UnwiredStaffPlanner:
    """Duck-types `StaffPlannerPort`."""

    async def plan(self, ctx, *, intent: str, message: str) -> StaffPlan:
        raise NotImplementedError(
            "UnwiredStaffPlanner is a placeholder -- wire a real StaffPlannerPort "
            "implementation (tasks.md Phase 12, LLM wiring) before staff_agent runs for real."
        )


class UnwiredAffirmationClassifier:
    """Duck-types `AffirmationClassifierPort`."""

    async def classify(self, ctx, message: str, *, pending_action_summary: str) -> AffirmationResult:
        raise NotImplementedError(
            "UnwiredAffirmationClassifier is a placeholder -- wire a real AffirmationClassifierPort "
            "implementation (tasks.md Phase 12, LLM wiring) before confirmation_gate runs for real."
        )


class UnwiredDirectResponse:
    """Duck-types `DirectResponsePort`."""

    async def respond(self, ctx, *, intent: str, message: str, allowed_actions) -> DirectResponsePlan:
        raise NotImplementedError(
            "UnwiredDirectResponse is a placeholder -- wire a real DirectResponsePort "
            "implementation (tasks.md task 12.5, Tony's system prompt) before direct_respond runs for real."
        )


class UnwiredSuggestionGenerator:
    """Duck-types `SuggestionGeneratorPort`. Returning an empty list (rather
    than raising) is the deliberate default here -- unlike every other
    Unwired* placeholder above, `respond` is meant to degrade gracefully with
    NO suggestions rather than fail the whole turn just because tasks.md task
    12.7's proactive-suggestion LLM tier is not wired yet; `suggestions:
    None` is an explicitly VALID, documented outcome (design.md §8.11.2:
    "no obligatorias"), unlike an unwired classifier/planner silently
    fabricating a decision it has no basis for."""

    async def generate(self, ctx, *, context) -> list[SuggestionCandidate]:
        return []
