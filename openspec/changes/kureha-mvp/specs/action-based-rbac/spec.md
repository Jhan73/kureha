# Action-Based RBAC Specification (action-based-rbac)

## Purpose

Authorization evaluated per concrete action (not just per role), configurable per tenant, deny-by-default. Roles are permission templates, not hardcoded capabilities. This is a second, independent authorization plane on top of `role-based-rls`: RLS resolves *what rows are visible*; this spec resolves *what operations may be executed* on rows already visible. RBAC MUST NEVER widen what RLS denies — RLS is the hard floor (see `access-control/spec.md`).

## Requirements

### Requirement: Action-Level Permission Evaluation

Every domain use case MUST check a permission for the tuple (`tenant_id`, actor role/user, action) before executing, at the domain/use-case layer — not only at the UI or API-routing layer. An action with no configured permission rule MUST be denied by default.

#### Scenario: Permitted action executes

- GIVEN a `reception` user at tenant T1 with permission `appointment:reschedule` granted
- WHEN they submit a reschedule
- THEN the use case executes normally

#### Scenario: Action without configured permission is denied

- GIVEN an action exists in the system but tenant T1 has no rule configured for role `reception` on that action
- WHEN a `reception` user attempts it
- THEN it MUST be denied — absence of a rule is NOT treated as implicit allow

#### Scenario: Direct API call bypassing UI is still denied

- GIVEN a `reception` user lacks permission for `appointment:cancel` without approval
- WHEN they invoke the underlying use case directly (not through any UI affordance)
- THEN the domain layer MUST deny the call with the same result as if attempted through the UI
- AND the denial MUST be audited

### Requirement: RBAC Must Not Widen RLS

A granted action permission MUST NOT make an out-of-scope row (per `role-based-rls`) accessible or actionable. RLS is evaluated first and independently.

#### Scenario: Permission granted but row out of RLS scope

- GIVEN a user holds permission for `appointment:view`
- WHEN they request an appointment belonging to a different tenant or a site outside their session scope
- THEN the request MUST be denied by RLS regardless of the RBAC grant

#### Scenario: Cross-tenant action attempt

- GIVEN a user holds the `appointment:cancel` permission at tenant T1
- WHEN they attempt to cancel an appointment belonging to tenant T2
- THEN the action MUST be denied — the permission grant is scoped to T1 only and never extends across tenants

### Requirement: Configurable Permission Matrix per Tenant

The system MUST allow each tenant to configure its own action-permission matrix per role (e.g. "reception can reschedule but not cancel without approval") without requiring a code change. Roles act as reusable permission templates.

#### Scenario: Tenant customizes a rule

- GIVEN tenant T1 configures `appointment:cancel` as requiring HITL approval for role `reception`
- WHEN a `reception` user at T1 attempts to cancel
- THEN the system MUST route through the HITL approval flow before executing
- AND a different tenant T2 without that rule is unaffected

#### Scenario: Same role template reused across sites

- GIVEN a `professional` role template is defined once for tenant T1
- WHEN it is applied to users at sede A and sede B within T1
- THEN both users get the same action permissions, scoped independently by RLS to their own site's data

### Requirement: Permission Cache Invalidation Is a Security Control, Not a Performance Concern

If permission resolution (`AuthorizeAction` / `ListAllowedActions`) is cached, the cache MUST be invalidated as part of the same operation that changes a `role_permissions` or `user_permissions` row. The system MUST NOT serve a stale, more-permissive cached result to any request after the change commits — a stale "allowed" response after a revoke is a privilege-escalation vulnerability, not a performance defect. See `platform-hardening` for the general tenant-scoped cache constraint this specializes.

#### Scenario: Permission revoked invalidates cache immediately

- GIVEN a reception user's permission resolution for `appointment:cancel` is cached as allowed
- WHEN an admin revokes that permission (`role_permissions` or `user_permissions` changes)
- THEN the very next `AuthorizeAction` call for that actor and action MUST NOT return the stale allowed result
- AND the revoked state MUST be reflected before any further mutating request executes

#### Scenario: Cache never substitutes for a live RLS check

- GIVEN a cached RBAC "allowed" result
- WHEN a request executes the authorized use case
- THEN RLS MUST still be evaluated live against the database — the cache MUST NOT be used to skip or pre-approve row-level visibility