# Session Management Specification (session-management)

## Purpose

Session lifecycle after authentication (see `user-authentication`): access token expiry, refresh, logout/revocation, and how a mid-session role/permission change is enforced. Extends the claim-propagation mechanism already defined in `access-control` ("Session Context Propagation") with a full lifecycle.

## Requirements

### Requirement: Short-Lived Access Tokens

Access tokens MUST have a short, bounded validity period (target: minutes, not hours) so that any claim baked into the token (role, permissions) has a small maximum staleness window.

#### Scenario: Expired access token is rejected

- GIVEN an access token issued longer ago than its validity window
- WHEN it is presented to any endpoint
- THEN the request MUST be rejected and a refresh MUST be required

### Requirement: Refresh Token Flow

The system MUST support refreshing an access token via a separate, longer-lived refresh token, without requiring the user to re-enter credentials. Refresh tokens MUST be revocable independently of access tokens.

#### Scenario: Refresh issues a new access token

- GIVEN a valid, unrevoked refresh token
- WHEN the client requests a refresh
- THEN a new short-lived access token is issued reflecting the user's current `tenant_id/site_id/role`

#### Scenario: Revoked refresh token cannot be used

- GIVEN a refresh token was revoked (logout or explicit revocation)
- WHEN it is presented to the refresh endpoint
- THEN the request MUST be denied

### Requirement: Logout and Revocation

Logout MUST revoke the associated refresh token so it can no longer be used to obtain new access tokens. The system MUST support explicit revocation of a session (e.g. by an admin) independent of user-initiated logout.

#### Scenario: User logs out

- GIVEN an authenticated user with an active refresh token
- WHEN they log out
- THEN the refresh token MUST be revoked immediately

#### Scenario: Admin revokes a session

- GIVEN an admin needs to terminate a specific user's session
- WHEN they trigger revocation
- THEN that user's refresh token(s) MUST be invalidated without affecting other users

### Requirement: Live Enforcement of Active Status (Critical — Overrides Token Claims)

Whether a user/staff account is `active` MUST be checked live against the database on every request, never solely from the access token's baked-in claims. Deactivating a user MUST take effect on that user's very next request, regardless of remaining access token TTL.

**Bound decision: next-request, not max-TTL.** Rationale: relying on token expiry alone would let a deactivated staff member keep acting for up to the full access-token lifetime. A live per-request check on `active` closes that window to zero, at the cost of one extra lookup per request — a cost already paid, since RBAC resolution is likewise live per request (`action-based-rbac`).

#### Scenario: Deactivated staff loses access immediately

- GIVEN a staff member has an active session with a valid, unexpired access token
- WHEN an admin deactivates that staff member
- THEN the staff member's very next request MUST be denied, even though their access token has not expired

#### Scenario: Reactivation restores access on next request

- GIVEN a previously deactivated staff member is reactivated
- WHEN they issue their next request with a still-valid token (or after refresh)
- THEN access MUST be restored without requiring a fresh login

### Requirement: Bounded Staleness for Role and Permission Claims

Role and permission changes that do not flip `active` status (e.g. a promotion) MUST take effect no later than the access token's validity window (per Short-Lived Access Tokens). RBAC action-permission checks MUST additionally be resolved live per request (per `action-based-rbac`), independent of any role claim baked into the token.

#### Scenario: Role change reflected within one token cycle

- GIVEN a staff member's role changes from `reception` to `admin`
- WHEN their current access token expires and they refresh
- THEN the new access token MUST reflect the updated role
- AND action-level permission checks in the interim MUST already reflect the change, since those are resolved live, not from the token
