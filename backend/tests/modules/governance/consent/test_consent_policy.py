from datetime import datetime, timezone

from app.modules.governance.consent.domain.consent import Consent
from app.modules.governance.consent.domain.consent_policy import (
    ConsentCheckResult,
    ConsentPolicy,
)

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _consent(*, status: str, policy_version: str) -> Consent:
    return Consent(
        id="c1",
        tenant_id="t1",
        site_id="s1",
        patient_id="p1",
        policy_version=policy_version,
        status=status,
        document_hash="hash",
        channel="web",
        actor_id=None,
        accepted_at=_NOW,
        revoked_at=_NOW if status == "revoked" else None,
    )


def test_no_consent_row_is_missing() -> None:
    assert ConsentPolicy.evaluate(current_version="2026.1", consent=None) == ConsentCheckResult.MISSING


def test_revoked_consent_is_missing() -> None:
    consent = _consent(status="revoked", policy_version="2026.1")

    assert ConsentPolicy.evaluate(current_version="2026.1", consent=consent) == ConsentCheckResult.MISSING


def test_accepted_consent_for_an_older_version_is_outdated() -> None:
    consent = _consent(status="accepted", policy_version="2025.1")

    assert ConsentPolicy.evaluate(current_version="2026.1", consent=consent) == ConsentCheckResult.OUTDATED


def test_accepted_consent_matching_the_current_version_is_current() -> None:
    consent = _consent(status="accepted", policy_version="2026.1")

    assert ConsentPolicy.evaluate(current_version="2026.1", consent=consent) == ConsentCheckResult.CURRENT


def test_no_published_current_policy_with_an_accepted_consent_is_outdated() -> None:
    consent = _consent(status="accepted", policy_version="2026.1")

    assert ConsentPolicy.evaluate(current_version=None, consent=consent) == ConsentCheckResult.OUTDATED
