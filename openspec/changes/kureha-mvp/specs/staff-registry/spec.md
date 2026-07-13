# Staff Registry Specification (staff-registry)

## Purpose

Operational personnel registry per sede: create and deactivate staff records. This is explicitly **NOT** full HR — no payroll, contracts, or performance-evaluation scenarios are in scope.

## Requirements

### Requirement: Personnel Create/Deactivate per Site

Authorized users (per `action-based-rbac`) MUST be able to register and deactivate staff, scoped to a `tenant_id` + `site_id`. Deactivated staff MUST NOT authenticate and MUST NOT be assignable to new appointments or shifts.

#### Scenario: Staff created and scoped correctly

- GIVEN an admin user at tenant T1, sede A creates a staff record
- WHEN another user at tenant T1, sede B queries staff
- THEN the new record MUST NOT be visible to sede B (RLS applies identically to staff data)

#### Scenario: Cross-tenant staff leak attempt blocked

- GIVEN a staff record belongs to tenant T1
- WHEN a user authenticated under tenant T2 queries it by id
- THEN access MUST be denied, consistent with `role-based-rls`

#### Scenario: Deactivated staff cannot be scheduled

- GIVEN a staff member is deactivated
- WHEN a scheduling flow attempts to assign them to a new appointment
- THEN the assignment MUST be rejected

### Requirement: Out-of-HR-Scope Boundary

The registry MUST NOT implement payroll, contract management, or performance-evaluation features. Registry data is limited to identity, operational status (active/inactive), site assignment, and role/permission-template assignment.

#### Scenario: Out-of-scope data rejected

- GIVEN a request attempts to record salary, contract terms, or a performance review through the staff registry
- WHEN it is submitted
- THEN the system MUST reject it as unsupported — this data has no field or use case in the MVP registry

### Requirement: Registry Changes Audited

Every create or deactivate action MUST be recorded to the append-only audit log with actor, `tenant_id`, `site_id`, and timestamp.

#### Scenario: Deactivation is audited

- GIVEN an admin deactivates a staff member
- WHEN the transaction commits
- THEN an audit row recording the actor and the deactivated staff id is committed together with it