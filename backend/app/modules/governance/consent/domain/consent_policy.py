"""`ConsentPolicy`: the pure business rule behind `CheckConsent` (design.md
§11) -- resolves the three outcomes the spec requires (current/missing/
outdated) from the tenant's current policy version and the patient's latest
consent row. Named `ConsentPolicy` (not `ConsentPolicyVersion`, the DB-row
entity in `consent.py`) to match this module's `Consent`/`ConsentPolicy`
naming from tasks.md task 3.2 and the same "XPolicy = pure evaluator"
convention used elsewhere in design.md (`RiskPolicy`, `StaffPolicy`,
`PermissionPolicy`)."""

from enum import Enum

from app.modules.governance.consent.domain.consent import Consent


class ConsentCheckResult(str, Enum):
    """The three outcomes design.md §11 names explicitly ("tres salidas
    (vigente/faltante/desactualizado)"). What happens on MISSING/OUTDATED
    (block + audited escalation) is the `consent_gate` LangGraph node's
    concern (tasks.md Phase 11), out of scope for this use case."""

    CURRENT = "current"
    MISSING = "missing"
    OUTDATED = "outdated"


class ConsentPolicy:
    """Stateless business rule -- no constructor, no IO."""

    @staticmethod
    def evaluate(*, current_version: str | None, consent: Consent | None) -> ConsentCheckResult:
        """A revoked consent is treated the same as no consent at all: the
        patient must re-consent, regardless of which version they revoked.
        An accepted consent for a version other than the tenant's current
        one -- including when there is no published current version at all
        -- is OUTDATED rather than silently CURRENT, since we cannot
        confirm the patient accepted whatever the current text says."""
        if consent is None or consent.status == "revoked":
            return ConsentCheckResult.MISSING
        if current_version is None or consent.policy_version != current_version:
            return ConsentCheckResult.OUTDATED
        return ConsentCheckResult.CURRENT
