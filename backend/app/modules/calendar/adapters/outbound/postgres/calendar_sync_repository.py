from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.modules.calendar.domain.calendar_sync_record import CalendarSyncRecord, CalendarSyncStatus

_SELECT = (
    "SELECT id, tenant_id, site_id, appointment_id, idempotency_key, google_event_id, "
    "sync_status, attempts, last_error, updated_at FROM calendar_sync"
)


class PostgresCalendarSyncRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def get_by_appointment(self, tenant_id: str, appointment_id: str) -> CalendarSyncRecord | None:
        result = await self._conn.execute(
            text(_SELECT + " WHERE tenant_id = :tenant_id AND appointment_id = :appointment_id"),
            {"tenant_id": tenant_id, "appointment_id": appointment_id},
        )
        row = result.first()
        return self._row_to_record(row) if row is not None else None

    async def get_or_create(
        self, tenant_id: str, site_id: str, appointment_id: str, *, idempotency_key: str
    ) -> CalendarSyncRecord:
        result = await self._conn.execute(
            text(
                "INSERT INTO calendar_sync (tenant_id, site_id, appointment_id, idempotency_key) "
                "VALUES (:tenant_id, :site_id, :appointment_id, :idempotency_key) "
                "ON CONFLICT (appointment_id) DO UPDATE SET site_id = EXCLUDED.site_id "
                "RETURNING id, tenant_id, site_id, appointment_id, idempotency_key, google_event_id, "
                "sync_status, attempts, last_error, updated_at"
            ),
            {
                "tenant_id": tenant_id,
                "site_id": site_id,
                "appointment_id": appointment_id,
                "idempotency_key": idempotency_key,
            },
        )
        row = result.one()
        return self._row_to_record(row)

    async def mark_ok(self, tenant_id: str, appointment_id: str, *, google_event_id: str) -> CalendarSyncRecord:
        result = await self._conn.execute(
            text(
                "UPDATE calendar_sync SET sync_status = 'ok', google_event_id = :google_event_id, "
                "last_error = NULL, updated_at = now() "
                "WHERE tenant_id = :tenant_id AND appointment_id = :appointment_id "
                "RETURNING id, tenant_id, site_id, appointment_id, idempotency_key, google_event_id, "
                "sync_status, attempts, last_error, updated_at"
            ),
            {"tenant_id": tenant_id, "appointment_id": appointment_id, "google_event_id": google_event_id},
        )
        return self._row_to_record(result.one())

    async def mark_failed(self, tenant_id: str, appointment_id: str, *, error: str) -> CalendarSyncRecord:
        result = await self._conn.execute(
            text(
                "UPDATE calendar_sync SET sync_status = 'failed', attempts = attempts + 1, "
                "last_error = :error, updated_at = now() "
                "WHERE tenant_id = :tenant_id AND appointment_id = :appointment_id "
                "RETURNING id, tenant_id, site_id, appointment_id, idempotency_key, google_event_id, "
                "sync_status, attempts, last_error, updated_at"
            ),
            {"tenant_id": tenant_id, "appointment_id": appointment_id, "error": error},
        )
        return self._row_to_record(result.one())

    async def list_due_for_retry(self, tenant_id: str, *, max_attempts: int) -> list[CalendarSyncRecord]:
        result = await self._conn.execute(
            text(
                _SELECT + " WHERE tenant_id = :tenant_id AND sync_status IN ('pending', 'failed') "
                "AND attempts < :max_attempts"
            ),
            {"tenant_id": tenant_id, "max_attempts": max_attempts},
        )
        return [self._row_to_record(row) for row in result.all()]

    @staticmethod
    def _row_to_record(row) -> CalendarSyncRecord:
        return CalendarSyncRecord(
            id=str(row.id),
            tenant_id=str(row.tenant_id),
            site_id=str(row.site_id),
            appointment_id=str(row.appointment_id),
            idempotency_key=row.idempotency_key,
            status=CalendarSyncStatus(row.sync_status),
            attempts=row.attempts,
            updated_at=row.updated_at,
            google_event_id=row.google_event_id,
            last_error=row.last_error,
        )
