import sqlalchemy as sa

from app.modules.governance.consent.adapters.outbound.postgres.consent_registry import (
    PostgresConsentRegistry,
)
from tests.rls.helpers import seed_consent, seed_consent_policy, seed_patient, seed_site, seed_tenant, set_app_context


class _CountingConn:
    """Wraps an `AsyncConnection` to count `.execute()` calls."""

    def __init__(self, conn) -> None:
        self._conn = conn
        self.calls = 0

    async def execute(self, *args, **kwargs):
        self.calls += 1
        return await self._conn.execute(*args, **kwargs)


async def test_get_current_policy_returns_the_tenants_current_version(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    await seed_consent_policy(rls_conn, tenant_id, version="2026.1", is_current=True)

    await set_app_context(rls_conn, tenant_id=tenant_id, role="admin")
    registry = PostgresConsentRegistry(rls_conn)

    policy = await registry.get_current_policy(tenant_id)

    assert policy is not None
    assert policy.version == "2026.1"
    assert policy.is_current is True


async def test_get_current_policy_returns_none_when_tenant_has_none(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)

    await set_app_context(rls_conn, tenant_id=tenant_id, role="admin")
    registry = PostgresConsentRegistry(rls_conn)

    assert await registry.get_current_policy(tenant_id) is None


async def test_get_current_policy_is_tenant_scoped(rls_conn) -> None:
    tenant_a = await seed_tenant(rls_conn)
    tenant_b = await seed_tenant(rls_conn)
    await seed_consent_policy(rls_conn, tenant_b, version="2026.1", is_current=True)

    await set_app_context(rls_conn, tenant_id=tenant_a, role="admin")
    registry = PostgresConsentRegistry(rls_conn)

    assert await registry.get_current_policy(tenant_a) is None


async def test_get_latest_consent_returns_the_patients_row(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    await seed_consent_policy(rls_conn, tenant_id, version="2026.1", is_current=True)
    patient_id = await seed_patient(rls_conn, tenant_id, site_id)
    await seed_consent(rls_conn, tenant_id, site_id, patient_id, policy_version="2026.1")

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception")
    registry = PostgresConsentRegistry(rls_conn)

    consent = await registry.get_latest_consent(tenant_id, patient_id)

    assert consent is not None
    assert consent.patient_id == patient_id
    assert consent.status == "accepted"
    assert consent.policy_version == "2026.1"


async def test_get_latest_consent_returns_none_when_patient_never_consented(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    patient_id = await seed_patient(rls_conn, tenant_id, site_id)

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception")
    registry = PostgresConsentRegistry(rls_conn)

    assert await registry.get_latest_consent(tenant_id, patient_id) is None


async def test_get_consent_check_data_returns_both_in_a_single_query(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    await seed_consent_policy(rls_conn, tenant_id, version="2026.1", is_current=True)
    patient_id = await seed_patient(rls_conn, tenant_id, site_id)
    await seed_consent(rls_conn, tenant_id, site_id, patient_id, policy_version="2026.1")

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception")
    counting_conn = _CountingConn(rls_conn)
    registry = PostgresConsentRegistry(counting_conn)

    policy, consent = await registry.get_consent_check_data(tenant_id, patient_id)

    assert counting_conn.calls == 1
    assert policy is not None
    assert policy.version == "2026.1"
    assert consent is not None
    assert consent.patient_id == patient_id
    assert consent.status == "accepted"


async def test_get_latest_consent_is_deterministic_when_accepted_at_ties(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    await seed_consent_policy(rls_conn, tenant_id, version="2026.1", is_current=True)
    patient_id = await seed_patient(rls_conn, tenant_id, site_id)

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception")
    for doc_hash in ("hash-1", "hash-2"):
        await rls_conn.execute(
            sa.text(
                "INSERT INTO consents "
                "(tenant_id, site_id, patient_id, policy_version, status, document_hash, channel, accepted_at) "
                "VALUES (:t, :s, :p, '2026.1', 'accepted', :hash, 'web', '2026-01-01T00:00:00Z')"
            ),
            {"t": tenant_id, "s": site_id, "p": patient_id, "hash": doc_hash},
        )

    registry = PostgresConsentRegistry(rls_conn)
    first_call = await registry.get_latest_consent(tenant_id, patient_id)
    second_call = await registry.get_latest_consent(tenant_id, patient_id)

    assert first_call is not None
    assert first_call.id == second_call.id  # same tied row every time, not planner-dependent


async def test_get_consent_check_data_returns_none_none_when_nothing_exists(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    patient_id = await seed_patient(rls_conn, tenant_id, site_id)

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception")
    registry = PostgresConsentRegistry(rls_conn)

    policy, consent = await registry.get_consent_check_data(tenant_id, patient_id)

    assert policy is None
    assert consent is None
