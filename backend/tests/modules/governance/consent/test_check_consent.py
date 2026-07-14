"""Task 3.2: `CheckConsent` use case -- orchestrates `ConsentRegistryPort` +
`ConsentPolicy`, no IO of its own (fake port, no DB)."""

from datetime import datetime, timezone

import pytest

from app.modules.governance.consent.application.use_cases.check_consent import CheckConsent
from app.modules.governance.consent.domain.consent import Consent, ConsentPolicyVersion
from app.modules.governance.consent.domain.consent_policy import ConsentCheckResult
from app.shared_kernel.tenant_context import TenantContext

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _FakeConsentRegistry:
    def __init__(self, *, policy: ConsentPolicyVersion | None, consent: Consent | None) -> None:
        self._policy = policy
        self._consent = consent

    async def get_current_policy(self, tenant_id: str) -> ConsentPolicyVersion | None:
        return self._policy

    async def get_latest_consent(self, tenant_id: str, patient_id: str) -> Consent | None:
        return self._consent

    async def get_consent_check_data(
        self, tenant_id: str, patient_id: str
    ) -> tuple[ConsentPolicyVersion | None, Consent | None]:
        return self._policy, self._consent


def _ctx() -> TenantContext:
    return TenantContext(tenant_id="t1", role="reception", site_id="s1", actor_id="u1")


@pytest.mark.asyncio
async def test_returns_missing_when_patient_has_no_consent() -> None:
    registry = _FakeConsentRegistry(
        policy=ConsentPolicyVersion(
            tenant_id="t1", version="2026.1", document_hash="h", is_current=True, published_at=_NOW
        ),
        consent=None,
    )
    use_case = CheckConsent(registry)

    result = await use_case.execute(_ctx(), patient_id="p1")

    assert result == ConsentCheckResult.MISSING


@pytest.mark.asyncio
async def test_returns_current_when_patient_accepted_the_current_version() -> None:
    registry = _FakeConsentRegistry(
        policy=ConsentPolicyVersion(
            tenant_id="t1", version="2026.1", document_hash="h", is_current=True, published_at=_NOW
        ),
        consent=Consent(
            id="c1",
            tenant_id="t1",
            site_id="s1",
            patient_id="p1",
            policy_version="2026.1",
            status="accepted",
            document_hash="h",
            channel="web",
            actor_id=None,
            accepted_at=_NOW,
            revoked_at=None,
        ),
    )
    use_case = CheckConsent(registry)

    result = await use_case.execute(_ctx(), patient_id="p1")

    assert result == ConsentCheckResult.CURRENT
