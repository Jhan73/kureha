from app.shared_kernel.errors import ConflictError, NotFoundError, ValidationError


class StaffMemberNotFoundError(NotFoundError):
    """No `staff_members` row matches the given id within the tenant."""


class StaffMemberNotActiveError(ValidationError):
    """Staff exists but is not active; cannot assign to a new shift."""


class ShiftNotFoundError(NotFoundError):
    """No `shifts` row matches the given id within the tenant."""


class ShiftOverlapError(ConflictError):
    """Shift window overlaps an existing shift for the same staff member."""
