"""Scheduling-module error hierarchy, subclassing `shared_kernel.errors` the
same way every other module does -- never a bare `DomainError`."""

from app.shared_kernel.errors import ConflictError, NotFoundError, ValidationError


class AppointmentNotFoundError(NotFoundError):
    """No `appointments` row matches the given id within the tenant."""


class AppointmentNotActiveError(ValidationError):
    """The appointment exists but is not in an active state (`scheduled` or
    `rescheduled`, design.md §4.1) -- reschedule/cancel are only valid
    transitions from an active appointment."""


class AvailabilitySlotNotFoundError(NotFoundError):
    """No `availability` row matches the given id within the tenant."""


class SlotUnavailableError(ConflictError):
    """The targeted `availability` slot is not `available` -- already
    reserved/blocked by someone else, or raced by a concurrent booking
    (design.md §4.1's `EXCLUDE USING gist` anti double-booking floor;
    spec `appointment-scheduling` -> "Double-booking prevented under
    concurrency": the losing request MUST fail and receive alternative-slot
    suggestions, which this error's caller is responsible for offering)."""


class StaffNotAssignableError(ValidationError):
    """The targeted professional is not currently assignable to a new
    appointment (spec `staff-registry` -> "Deactivated staff cannot be
    scheduled": deactivation in the `staff` module MUST NOT let scheduling
    keep booking that professional). Resolved via `StaffStatusPort`
    (application/ports/driven/staff_status_port.py, tasks.md task 8.4) --
    scheduling never imports `modules.staff` directly (business modules
    never import each other's internals, backend/AGENTS.md); this error is
    raised from scheduling's own use cases based purely on the port's
    boolean answer, before any appointment mutation is attempted."""
