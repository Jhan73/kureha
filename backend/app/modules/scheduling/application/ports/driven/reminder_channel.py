from typing import Protocol

from app.modules.scheduling.domain.appointment import Appointment


class ReminderChannelPort(Protocol):
    async def send(self, appointment: Appointment, *, patient_id: str) -> bool:
        """Attempts to dispatch a reminder for `appointment`. Returns
        `True`/`False` for delivered/failed -- never raises for an ordinary
        delivery failure (spec: "Channel port failure does not break
        scheduling flows"); `SendReminder` treats both outcomes as a
        successful *use case* execution, only the delivery outcome differs,
        and both are logged to the audit trail."""
        ...
