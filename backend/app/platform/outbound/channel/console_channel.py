"""`ConsoleReminderChannel`: MVP `ReminderChannelPort` implementation
(design.md §2.5's `platform/outbound/channel/` -- "ConsoleChannel
notificaciones (MVP) | WhatsAppChannel (V2)"), closing the gap
`reminder_channel.py`'s own module docstring flags: "no concrete adapter
ships in this PR... whichever future task wires the composition root (task
10.2) MUST supply a concrete `ReminderChannelPort` implementation, or
`SendReminder` has nothing to construct against in production."

Deliberately trivial -- logs the reminder to stdout via stdlib `logging`
(same convention `errors.py`/`audit_safety.py` use for server-side-only
detail) and always reports delivery as successful. No real patient-facing
channel (SMS/WhatsApp/email) exists yet; `SendReminder`'s own contract
already treats a channel failure as non-fatal (spec `appointment-scheduling`
-> "Channel port failure does not break scheduling flows"), so a
stdout-only stand-in is a safe MVP default, not a shortcut around that
contract -- design.md's own "V2" label on `WhatsAppChannel` confirms a real
channel is intentionally out of MVP scope."""

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
