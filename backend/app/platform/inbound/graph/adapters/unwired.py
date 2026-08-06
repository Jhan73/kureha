from app.platform.inbound.graph.ports.affirmation_classifier import AffirmationResult
from app.platform.inbound.graph.ports.direct_response import DirectResponsePlan
from app.platform.inbound.graph.ports.intent_classifier import IntentClassificationResult
from app.platform.inbound.graph.ports.reminder_planner import ReminderPlan
from app.platform.inbound.graph.ports.scheduling_planner import SchedulingPlan
from app.platform.inbound.graph.ports.staff_planner import StaffPlan
from app.platform.inbound.graph.ports.suggestion_generator import SuggestionCandidate


class UnwiredIntentClassifier:
    """Placeholder; raises until a real IntentClassifierPort is wired."""

    async def classify(self, ctx, message: str) -> IntentClassificationResult:
        raise NotImplementedError(
            "UnwiredIntentClassifier is a placeholder -- wire a real IntentClassifierPort "
            "before a real chat turn reaches triage."
        )


class UnwiredSchedulingPlanner:
    """Placeholder; raises until a real SchedulingPlannerPort is wired."""

    async def plan(self, ctx, *, intent: str, message: str) -> SchedulingPlan:
        raise NotImplementedError(
            "UnwiredSchedulingPlanner is a placeholder -- wire a real SchedulingPlannerPort "
            "before scheduling_agent runs for real."
        )


class UnwiredReminderPlanner:
    """Placeholder; raises until a real ReminderPlannerPort is wired."""

    async def plan(self, ctx, *, message: str) -> ReminderPlan:
        raise NotImplementedError(
            "UnwiredReminderPlanner is a placeholder -- wire a real ReminderPlannerPort "
            "before reminders_agent runs for real."
        )


class UnwiredStaffPlanner:
    """Placeholder; raises until a real StaffPlannerPort is wired."""

    async def plan(self, ctx, *, intent: str, message: str) -> StaffPlan:
        raise NotImplementedError(
            "UnwiredStaffPlanner is a placeholder -- wire a real StaffPlannerPort "
            "before staff_agent runs for real."
        )


class UnwiredAffirmationClassifier:
    """Placeholder; raises until a real AffirmationClassifierPort is wired."""

    async def classify(self, ctx, message: str, *, pending_action_summary: str) -> AffirmationResult:
        raise NotImplementedError(
            "UnwiredAffirmationClassifier is a placeholder -- wire a real AffirmationClassifierPort "
            "before confirmation_gate runs for real."
        )


class UnwiredDirectResponse:
    """Placeholder; raises until a real DirectResponsePort is wired."""

    async def respond(self, ctx, *, intent: str, message: str, allowed_actions) -> DirectResponsePlan:
        raise NotImplementedError(
            "UnwiredDirectResponse is a placeholder -- wire a real DirectResponsePort "
            "before direct_respond runs for real."
        )


class UnwiredSuggestionGenerator:
    """Placeholder; returns [] so respond can proceed without suggestions."""

    async def generate(self, ctx, *, context) -> list[SuggestionCandidate]:
        return []
