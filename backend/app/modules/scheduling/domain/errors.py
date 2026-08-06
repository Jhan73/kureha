from app.shared_kernel.errors import ConflictError, NotFoundError, ValidationError


class AppointmentNotFoundError(NotFoundError):
    """No `appointments` row matches the given id within the tenant."""


class AppointmentNotActiveError(ValidationError):
    """Appointment exists but is not scheduled/rescheduled."""


class AvailabilitySlotNotFoundError(NotFoundError):
    """No `availability` row matches the given id within the tenant."""


class SlotUnavailableError(ConflictError):
    """Slot not available (reserved/blocked or concurrent booking race)."""


class StaffNotAssignableError(ValidationError):
    """Professional not assignable (via StaffStatusPort; no staff-module import)."""
