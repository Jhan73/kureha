"""`RiskPolicy` (design.md §8.4): pure rules deriving `risk_level` for the
graph's `hitl_approval` interrupt trigger inventory --

1. bulk cancellation of MORE than `action_permissions.bulk_cancel_threshold`
   appointments in one intent (design.md §4.4's `bulk_cancel_threshold int
   NOT NULL DEFAULT 3`, §8.4: "si `len(proposed_action.appointment_ids) >
   threshold` entonces `risk_level='high'`"),
2. a reschedule that lands on a professional OTHER than the one the patient
   requested (spec `clinical-safety` -> "Professional reassignment requires
   approval").

No IO here by design (mirrors `PermissionPolicy`/`ConsentPolicy`/
`SessionPolicy`): the threshold value lives in the `action_permissions`
catalog (governance/rbac's table) and is resolved by whoever orchestrates the
decision -- the future `scheduling_agent` LangGraph node (tasks.md Phase 11,
not yet built) -- and handed to this policy already known. Scheduling's own
Phase 7 use cases (`schedule_appointment.py` et al.) do not call this policy
at all: HITL routing is entirely the graph's job, applied BEFORE those use
cases execute the already-approved mutation."""

from enum import Enum


class RiskLevel(str, Enum):
    LOW = "low"
    HIGH = "high"


class RiskPolicy:
    @staticmethod
    def evaluate_bulk_cancel(appointment_count: int, *, threshold: int) -> RiskLevel:
        """`> threshold` is masivo (design.md §8.4's exact wording), so a
        count equal to the threshold is still `LOW`."""
        return RiskLevel.HIGH if appointment_count > threshold else RiskLevel.LOW

    @staticmethod
    def evaluate_reschedule(*, requested_professional_id: str, target_professional_id: str) -> RiskLevel:
        """`HIGH` when the reschedule would land on a DIFFERENT professional
        than the one the patient explicitly requested -- if the patient
        agrees to the same professional as booked, no HITL step is needed
        (spec `clinical-safety`'s "Professional reassignment requires
        approval" scenario)."""
        if requested_professional_id != target_professional_id:
            return RiskLevel.HIGH
        return RiskLevel.LOW
