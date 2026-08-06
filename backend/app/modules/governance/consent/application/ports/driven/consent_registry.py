from typing import Protocol

from app.modules.governance.consent.domain.consent import Consent, ConsentPolicyVersion


class ConsentRegistryPort(Protocol):
    async def get_current_policy(self, tenant_id: str) -> ConsentPolicyVersion | None:
        """Current published policy, or None if none published."""
        ...

    async def get_latest_consent(self, tenant_id: str, patient_id: str) -> Consent | None:
        """Most recent accepted/revoked consent, or None."""
        ...

    async def get_consent_check_data(
        self, tenant_id: str, patient_id: str
    ) -> tuple[ConsentPolicyVersion | None, Consent | None]:
        """Both lookups in one round trip (hot path)."""
        ...
