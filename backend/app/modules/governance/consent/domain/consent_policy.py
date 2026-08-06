from enum import Enum

from app.modules.governance.consent.domain.consent import Consent


class ConsentCheckResult(str, Enum):
    CURRENT = "current"
    MISSING = "missing"
    OUTDATED = "outdated"


class ConsentPolicy:
    @staticmethod
    def evaluate(*, current_version: str | None, consent: Consent | None) -> ConsentCheckResult:
        """Revoked == missing; wrong/unknown version == outdated."""
        if consent is None or consent.status == "revoked":
            return ConsentCheckResult.MISSING
        if current_version is None or consent.policy_version != current_version:
            return ConsentCheckResult.OUTDATED
        return ConsentCheckResult.CURRENT
