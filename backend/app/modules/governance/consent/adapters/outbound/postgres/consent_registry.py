from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.modules.governance.consent.domain.consent import Consent, ConsentPolicyVersion


class PostgresConsentRegistry:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def get_current_policy(self, tenant_id: str) -> ConsentPolicyVersion | None:
        result = await self._conn.execute(
            text(
                "SELECT tenant_id, version, document_hash, is_current, published_at "
                "FROM consent_policies WHERE tenant_id = :tenant_id AND is_current"
            ),
            {"tenant_id": tenant_id},
        )
        row = result.first()
        if row is None:
            return None
        return ConsentPolicyVersion(
            tenant_id=str(row.tenant_id),
            version=row.version,
            document_hash=row.document_hash,
            is_current=row.is_current,
            published_at=row.published_at,
        )

    async def get_latest_consent(self, tenant_id: str, patient_id: str) -> Consent | None:
        # `id DESC` tiebreaks `accepted_at` ties deterministically (same tied
        # row every call) but NOT by true insertion order -- `consents.id`
        # is a random `gen_random_uuid()`, not a monotonic column, so this
        # cannot guarantee "the truly latest row wins" if two rows ever share
        # `accepted_at` exactly. `NULLS LAST` was dropped: `consents.accepted_at`
        # is NOT NULL by CHECK constraint (migration 5975cbe7665e), so it was
        # dead. No accept/revoke write path exists yet to actually produce a
        # tie -- flagged for whoever builds one to consider a monotonic
        # tiebreaker column if this matters in practice.
        result = await self._conn.execute(
            text(
                "SELECT id, tenant_id, site_id, patient_id, policy_version, status, "
                "document_hash, channel, actor_id, accepted_at, revoked_at "
                "FROM consents "
                "WHERE tenant_id = :tenant_id AND patient_id = :patient_id "
                "ORDER BY accepted_at DESC, id DESC LIMIT 1"
            ),
            {"tenant_id": tenant_id, "patient_id": patient_id},
        )
        row = result.first()
        if row is None:
            return None
        return self._row_to_consent(row)

    async def get_consent_check_data(
        self, tenant_id: str, patient_id: str
    ) -> tuple[ConsentPolicyVersion | None, Consent | None]:
        """`get_current_policy` + `get_latest_consent` in one round trip.
        The two are independent lookups with no shared join key, so this
        uses two `LEFT JOIN LATERAL` subqueries (each capped at one row)
        against a single-row driving table, rather than two sequential
        SELECTs -- see `CheckConsent`'s docstring for why this exists
        instead of `asyncio.gather`-ing the two separate methods above."""
        result = await self._conn.execute(
            text(
                """
                SELECT
                    cp.tenant_id AS cp_tenant_id, cp.version AS cp_version,
                    cp.document_hash AS cp_document_hash, cp.is_current AS cp_is_current,
                    cp.published_at AS cp_published_at,
                    c.id AS c_id, c.tenant_id AS c_tenant_id, c.site_id AS c_site_id,
                    c.patient_id AS c_patient_id, c.policy_version AS c_policy_version,
                    c.status AS c_status, c.document_hash AS c_document_hash,
                    c.channel AS c_channel, c.actor_id AS c_actor_id,
                    c.accepted_at AS c_accepted_at, c.revoked_at AS c_revoked_at
                FROM (SELECT 1) AS _driver
                LEFT JOIN LATERAL (
                    SELECT * FROM consent_policies
                    WHERE tenant_id = :tenant_id AND is_current
                    LIMIT 1
                ) AS cp ON true
                LEFT JOIN LATERAL (
                    SELECT * FROM consents
                    WHERE tenant_id = :tenant_id AND patient_id = :patient_id
                    ORDER BY accepted_at DESC, id DESC LIMIT 1
                ) AS c ON true
                """
            ),
            {"tenant_id": tenant_id, "patient_id": patient_id},
        )
        row = result.one()

        policy = None
        if row.cp_version is not None:
            policy = ConsentPolicyVersion(
                tenant_id=str(row.cp_tenant_id),
                version=row.cp_version,
                document_hash=row.cp_document_hash,
                is_current=row.cp_is_current,
                published_at=row.cp_published_at,
            )

        consent = None
        if row.c_id is not None:
            consent = Consent(
                id=str(row.c_id),
                tenant_id=str(row.c_tenant_id),
                site_id=str(row.c_site_id) if row.c_site_id is not None else None,
                patient_id=str(row.c_patient_id),
                policy_version=row.c_policy_version,
                status=row.c_status,
                document_hash=row.c_document_hash,
                channel=row.c_channel,
                actor_id=str(row.c_actor_id) if row.c_actor_id is not None else None,
                accepted_at=row.c_accepted_at,
                revoked_at=row.c_revoked_at,
            )

        return policy, consent

    @staticmethod
    def _row_to_consent(row) -> Consent:
        return Consent(
            id=str(row.id),
            tenant_id=str(row.tenant_id),
            site_id=str(row.site_id) if row.site_id is not None else None,
            patient_id=str(row.patient_id),
            policy_version=row.policy_version,
            status=row.status,
            document_hash=row.document_hash,
            channel=row.channel,
            actor_id=str(row.actor_id) if row.actor_id is not None else None,
            accepted_at=row.accepted_at,
            revoked_at=row.revoked_at,
        )
