# Staff Scheduling Specification (staff-scheduling)

## Purpose

Work schedules and shifts (horarios/turnos) per professional and per sede. Shift data feeds the availability rules that `appointment-scheduling` books against.

## Requirements

### Requirement: Shift Definition per Professional and Site

Authorized users MUST be able to define and edit work shifts scoped to `tenant_id` + `site_id` + professional. RLS applies to shift data exactly as it does to appointments.

#### Scenario: Shift not visible cross-site

- GIVEN a shift is defined for a professional at tenant T1, sede A
- WHEN a user at tenant T1, sede B queries that professional's shifts
- THEN no rows MUST be returned

### Requirement: Schedule Conflict Detection

The system MUST reject a new or edited shift that overlaps an existing conflicting shift or approved absence for the same professional. Appointment slots MUST be offered and booked only within the professional's currently defined shifts.

#### Scenario: Overlapping shift rejected

- GIVEN a professional already has a shift Monday 08:00-14:00 at sede A
- WHEN an admin attempts to create a second shift Monday 12:00-18:00 for the same professional
- THEN the system MUST reject it and reference the conflicting shift

#### Scenario: Appointment outside defined shift rejected

- GIVEN a professional's only shift on a given day ends at 14:00
- WHEN a booking is attempted for 15:00 that same day
- THEN it MUST be rejected as outside availability, consistent with `appointment-scheduling`

#### Scenario: Concurrent shift edits do not create overlap

- GIVEN two admins concurrently submit shifts for the same professional and overlapping time windows
- WHEN both are submitted at nearly the same time
- THEN only the first MUST succeed and the second MUST fail with the conflict reported — no overlapping shift is ever committed

### Requirement: Shift Changes Audited

Every shift create, edit, or delete MUST be recorded to the append-only audit log with actor, `tenant_id`, `site_id`, and affected professional.

#### Scenario: Shift edit is audited

- GIVEN an admin edits a professional's shift
- WHEN the transaction commits
- THEN an audit row is committed together with it