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
