"""`ReminderChannelPort` (design.md §2.5's `platform/outbound/channel/`,
spec `appointment-scheduling` -> "Reminders and Confirmations"'s "abstract
channel port"): the outbound side `SendReminder` (tasks.md task 7.3) depends
on to dispatch a confirmation/reminder message ahead of an appointment.

**No concrete adapter ships in this PR.** `design.md` §2.5 places the real
implementation (`ConsoleChannel` MVP / `WhatsAppChannel` V2) under
`app/platform/outbound/channel/`, but no `tasks.md` task builds it yet (the
closest is task 10.1's web-form routers and task 14.x's frontend views,
neither of which is "build the outbound reminder channel"). Flagged here,
not silently invented: whichever future task wires the composition root
(task 10.2) MUST supply a concrete `ReminderChannelPort` implementation, or
`SendReminder` has nothing to construct against in production."""

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
