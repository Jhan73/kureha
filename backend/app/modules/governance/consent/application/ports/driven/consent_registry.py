"""`ConsentRegistryPort` (design.md §12): the driven port `CheckConsent`
depends on. Implemented in MVP by `PostgresConsentRegistry`
(adapters/outbound/postgres/consent_registry.py)."""

from typing import Protocol

from app.modules.governance.consent.domain.consent import Consent, ConsentPolicyVersion


class ConsentRegistryPort(Protocol):
    async def get_current_policy(self, tenant_id: str) -> ConsentPolicyVersion | None:
        """The tenant's currently-published policy version, or `None` if the
        tenant has not published one yet (design.md §11/§16: the v1 legal
        text is a pending business input)."""
        ...

    async def get_latest_consent(self, tenant_id: str, patient_id: str) -> Consent | None:
        """The patient's most recently accepted-or-revoked consent row, or
        `None` if the patient has never consented."""
        ...

    async def get_consent_check_data(
        self, tenant_id: str, patient_id: str
    ) -> tuple[ConsentPolicyVersion | None, Consent | None]:
        """Both `get_current_policy(tenant_id)` and
        `get_latest_consent(tenant_id, patient_id)` in a single round trip --
        the two are independent lookups with no shared join key, so a real
        adapter should resolve them via one query (e.g. two `LEFT JOIN
        LATERAL` subqueries) rather than issuing two sequential SELECTs.
        `CheckConsent` (a hot path per design.md §11) uses this instead of
        calling the two methods above separately."""
        ...
