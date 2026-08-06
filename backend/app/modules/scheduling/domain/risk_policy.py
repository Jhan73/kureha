from enum import Enum


class RiskLevel(str, Enum):
    LOW = "low"
    HIGH = "high"


class RiskPolicy:
    @staticmethod
    def evaluate_bulk_cancel(appointment_count: int, *, threshold: int) -> RiskLevel:
        """HIGH only when count is strictly greater than threshold."""
        return RiskLevel.HIGH if appointment_count > threshold else RiskLevel.LOW

    @staticmethod
    def evaluate_reschedule(*, requested_professional_id: str, target_professional_id: str) -> RiskLevel:
        """HIGH when landing on a different professional than requested."""
        if requested_professional_id != target_professional_id:
            return RiskLevel.HIGH
        return RiskLevel.LOW
