"""Staff-module error hierarchy, subclassing `shared_kernel.errors` the same
way every other module does -- never a bare `DomainError`."""

from app.shared_kernel.errors import ConflictError, NotFoundError, ValidationError


class StaffMemberNotFoundError(NotFoundError):
    """No `staff_members` row matches the given id within the tenant."""


class StaffMemberNotActiveError(ValidationError):
    """The staff member exists but is not `active` -- design.md §6/spec
    `staff-registry`'s "Deactivated staff cannot be scheduled": a deactivated
    staff member MUST NOT be assignable to a new shift. (Assigning a
    deactivated professional to a new *appointment* is the `scheduling`
    module's concern -- out of scope here; business modules never import each
    other, design.md §2.4 -- flagged as a known gap for the future graph
    orchestration, tasks.md Phase 11, same class of gap as `RiskPolicy`'s
    threshold-resolution note.)"""


class ShiftNotFoundError(NotFoundError):
    """No `shifts` row matches the given id within the tenant."""


class ShiftOverlapError(ConflictError):
    """The requested shift window overlaps an existing shift for the same
    staff member -- design.md §4.4's `EXCLUDE USING gist` anti-overlap floor
    (spec `staff-scheduling` -> "Schedule Conflict Detection": the losing
    request MUST fail and reference the conflict)."""
