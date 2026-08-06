import inspect

from app.platform.inbound.graph.ports.affirmation_classifier import (
    AffirmationClassifierPort,
    AffirmationResult,
)
from app.platform.inbound.graph.ports.intent_classifier import (
    IntentClassificationResult,
    IntentClassifierPort,
)
from app.platform.inbound.graph.ports.reminder_planner import ReminderPlan, ReminderPlannerPort
from app.platform.inbound.graph.ports.scheduling_planner import SchedulingPlan, SchedulingPlannerPort
from app.platform.inbound.graph.ports.staff_planner import StaffPlan, StaffPlannerPort


def test_intent_classifier_port_is_an_async_protocol_taking_ctx_and_message() -> None:
    assert hasattr(IntentClassifierPort, "classify")
    assert inspect.iscoroutinefunction(IntentClassifierPort.classify)
    params = list(inspect.signature(IntentClassifierPort.classify).parameters)
    assert "ctx" in params
    assert "message" in params


def test_intent_classification_result_carries_intent() -> None:
    result = IntentClassificationResult(intent="schedule")

    assert result.intent == "schedule"


def test_scheduling_planner_port_is_an_async_protocol() -> None:
    assert hasattr(SchedulingPlannerPort, "plan")
    assert inspect.iscoroutinefunction(SchedulingPlannerPort.plan)


def test_scheduling_plan_carries_risk_relevant_fields() -> None:
    plan = SchedulingPlan(
        action="appointment:cancel_bulk",
        kwargs={"appointment_id": "a1"},
        summary="Cancel 5 appointments",
        appointment_ids=["a1", "a2", "a3", "a4", "a5"],
    )

    assert plan.action == "appointment:cancel_bulk"
    assert plan.appointment_ids is not None
    assert len(plan.appointment_ids) == 5
    assert plan.requested_professional_id is None


def test_reminder_planner_port_is_an_async_protocol() -> None:
    assert hasattr(ReminderPlannerPort, "plan")
    assert inspect.iscoroutinefunction(ReminderPlannerPort.plan)


def test_reminder_plan_carries_appointment_id_and_summary() -> None:
    plan = ReminderPlan(appointment_id="a1", summary="Remind about tomorrow's appointment")

    assert plan.appointment_id == "a1"


def test_staff_planner_port_is_an_async_protocol() -> None:
    assert hasattr(StaffPlannerPort, "plan")
    assert inspect.iscoroutinefunction(StaffPlannerPort.plan)


def test_staff_plan_carries_action_kwargs_and_summary() -> None:
    plan = StaffPlan(action="shift:create", kwargs={"staff_member_id": "s1"}, summary="Create a new shift")

    assert plan.action == "shift:create"
    assert plan.kwargs == {"staff_member_id": "s1"}


def test_affirmation_classifier_port_is_an_async_protocol_taking_ctx_message_and_summary() -> None:
    assert hasattr(AffirmationClassifierPort, "classify")
    assert inspect.iscoroutinefunction(AffirmationClassifierPort.classify)
    params = list(inspect.signature(AffirmationClassifierPort.classify).parameters)
    assert "ctx" in params
    assert "message" in params
    assert "pending_action_summary" in params


def test_affirmation_result_carries_a_three_way_decision() -> None:
    assert AffirmationResult(decision="affirmed").decision == "affirmed"
    assert AffirmationResult(decision="declined").decision == "declined"
    assert AffirmationResult(decision="unclear").decision == "unclear"
