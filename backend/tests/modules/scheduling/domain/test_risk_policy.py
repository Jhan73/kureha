"""Task 7.1: `RiskPolicy` -- pure rules deriving `risk_level` (design.md
§8.4's `hitl_approval` trigger inventory). No IO: the threshold value
(`action_permissions.bulk_cancel_threshold`, design.md §4.4) and the
requested/target professional ids are resolved by whoever calls this
(the future `scheduling_agent` LangGraph node, tasks.md Phase 11) and
passed in already-known."""

from app.modules.scheduling.domain.risk_policy import RiskLevel, RiskPolicy


def test_bulk_cancel_at_or_below_threshold_is_low_risk() -> None:
    assert RiskPolicy.evaluate_bulk_cancel(3, threshold=3) is RiskLevel.LOW


def test_bulk_cancel_above_threshold_is_high_risk() -> None:
    assert RiskPolicy.evaluate_bulk_cancel(4, threshold=3) is RiskLevel.HIGH


def test_bulk_cancel_of_a_single_appointment_is_low_risk_with_default_threshold() -> None:
    assert RiskPolicy.evaluate_bulk_cancel(1, threshold=3) is RiskLevel.LOW


def test_reschedule_to_the_same_requested_professional_is_low_risk() -> None:
    assert (
        RiskPolicy.evaluate_reschedule(requested_professional_id="p1", target_professional_id="p1")
        is RiskLevel.LOW
    )


def test_reschedule_to_a_different_professional_is_high_risk() -> None:
    assert (
        RiskPolicy.evaluate_reschedule(requested_professional_id="p1", target_professional_id="p2")
        is RiskLevel.HIGH
    )
