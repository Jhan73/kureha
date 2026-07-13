# Access Control Specification (role-based-rls)

## Purpose

Database-level isolation by **tenant + site + role** (patient, reception, professional, admin), independent of application logic, deny-by-default. `tenant_id` sits above `site_id` as an additional, mandatory scoping layer — not a replacement for it. This spec covers `role-based-rls` and `multi-tenant-isolation` (the tenant boundary is enforced by the same RLS mechanism, not a separate one — see `action-based-rbac/spec.md` for the companion authorization plane covering *what operations* an actor may execute on rows RLS already lets them see).

## Requirements

### Requirement: Row-Level Security by Tenant, Site and Role

The system MUST enforce Postgres RLS policies (with `FORCE ROW LEVEL SECURITY`) scoping every query to the requesting user's `tenant_id`, `site_id`, and role. The system MUST NOT rely solely on application-layer filtering to enforce this boundary, and MUST NOT ever execute patient-data queries under `BYPASSRLS`.

#### Scenario: Reception scoped to own tenant and site

- GIVEN a user with role `reception` at tenant T1, site A
- WHEN they query appointments
- THEN only rows belonging to tenant T1 AND site A are returned

#### Scenario: Cross-site access blocked within same tenant

- GIVEN a user with role `reception` at tenant T1, site A
- WHEN they query a resource belonging to tenant T1, site B
- THEN RLS returns zero rows
- AND the response MUST NOT reveal whether the record exists

#### Scenario: Cross-tenant leak attempt blocked

- GIVEN a user authenticated with tenant T1 claims
- WHEN they query, by guessed or enumerated id, a resource belonging to tenant T2 (a different clinic entirely, even if role and site labels coincide)
- THEN RLS MUST return zero rows regardless of role or site match
- AND the attempt MUST be recorded per the append-only-audit-log spec

#### Scenario: Patient restricted to own records

- GIVEN a user with role `patient`
- WHEN they query an appointment belonging to a different patient (same or different tenant)
- THEN access MUST be denied

#### Scenario: Deny by default on new resources

- GIVEN a new table or policy without an explicit grant for a `tenant_id` + `site_id` + role combination
- WHEN that role queries it
- THEN no rows MUST be returned until a policy explicitly allows it

### Requirement: Session Context Propagation

The system MUST set the database session's `tenant_id`, role, and site claims (via `SET LOCAL app.tenant_id`, `app.site_id`, `app.role` or equivalent GUCs) from the authenticated JWT before executing any query in that session. The system MUST NOT execute queries under a default or elevated database role.

#### Scenario: Missing session claims

- GIVEN a request whose JWT lacks a `tenant_id`, role, or site claim
- WHEN the request reaches the data layer
- THEN it MUST be rejected before any query executes
- AND the rejection MUST be recorded per the append-only-audit-log spec

### Requirement: RLS Violation Reporting

When a query is denied by RLS, the system MUST record the attempt (actor, tenant, resource requested, denial reason) to the append-only audit log and MUST NOT leak record existence in the denial response.

#### Scenario: Denied access is audited

- GIVEN an authenticated user
- WHEN a query is blocked by RLS
- THEN an audit entry, including `tenant_id`, is written in the same transaction
- AND the caller receives a generic denial, not a not-found vs forbidden distinction

### Requirement: RLS Is the Authorization Floor

RLS-resolved visibility MUST be evaluated independently of, and prior to, any action-based-rbac permission check. No RBAC permission grant MUST be capable of making a row visible that RLS would otherwise hide.

#### Scenario: Permitted action cannot bypass RLS

- GIVEN a staff user holds RBAC permission for action `appointment:view`
- WHEN they request an appointment belonging to a tenant or site outside their session scope
- THEN RLS denies the row before RBAC is even consulted
- AND the denial is audited as an RLS denial, not an RBAC denial

### Requirement: Session Claims Originate From Authenticated Identity

Session claims (`tenant_id`, `site_id`, `role`, `user_id`) projected into GUCs via `SET LOCAL` (see Session Context Propagation) MUST originate from a successful authentication performed through `AuthPort` (see `user-authentication`), not from an arbitrary or self-issued token. The system MUST map the authenticated identity to a `users` row that resolves `tenant_id/site_id/role` before any session claim is set.

#### Scenario: Claims resolved from authenticated identity

- GIVEN a request carries a token issued by `AuthPort` after successful authentication
- WHEN the session begins
- THEN `tenant_id`/`site_id`/`role`/`user_id` are resolved from the mapped `users` row, not trusted verbatim from arbitrary token content

#### Scenario: Token without a mapped identity is rejected

- GIVEN a token is valid per `AuthPort` but has no corresponding `users` row (identity not yet linked/provisioned)
- WHEN a request attempts to establish a session
- THEN the request MUST be rejected before any query executes
- AND the rejection MUST be audited
