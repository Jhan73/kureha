import logging

from app.modules.scheduling.domain.appointment import Appointment

logger = logging.getLogger(__name__)


class ConsoleReminderChannel:
    async def send(self, appointment: Appointment, *, patient_id: str) -> bool:
        logger.info(
            "reminder dispatched (console) appointment_id=%s patient_id=%s starts_at=%s",
            appointment.id,
            patient_id,
            appointment.starts_at,
        )
        return True
