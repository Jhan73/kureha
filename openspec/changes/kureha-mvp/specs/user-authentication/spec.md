# User Authentication Specification (user-authentication)

## Purpose

Authentication (proving identity) behind `AuthPort`, mirroring `CalendarSyncPort`. Supports email+password and federated "Sign in with Google" login. `AuthPort` resolves **authn** only; Kureha retains **authz context** — the `users` row mapping identity to `tenant_id/site_id/role` stays in Kureha's database and is projected to RLS GUCs as before (see `access-control`). This spec states requirements an identity-provider integration MUST satisfy; it does not select a vendor (an architectural decision already made in the proposal, concretized in `sdd-design`).

## Requirements

### Requirement: Email and Password Authentication

The system MUST support authentication via email and password. Passwords MUST be stored using a strong, adaptive, salted hash (never reversible encryption or plaintext), and MUST NOT appear in plaintext in logs, audit entries, or error messages. The system MUST enforce a minimum password strength policy at signup.

#### Scenario: Successful password login

- GIVEN a patient or staff user with a registered email+password
- WHEN they submit correct credentials
- THEN they receive an authenticated session per `session-management`

#### Scenario: Wrong password rejected without enumeration

- GIVEN an email that may or may not be registered
- WHEN a login attempt uses that email with an incorrect password
- THEN the system MUST return a generic authentication failure — it MUST NOT reveal whether the email exists

### Requirement: Federated Google Sign-In

The system MUST support "Sign in with Google" as an independent authentication method. A successful Google sign-in MUST resolve to (or create) exactly one `users` identity, using the Google account's verified email for linking.

#### Scenario: First-time Google sign-in creates an account

- GIVEN no existing user matches the Google account's verified email
- WHEN a patient signs in with Google for the first time
- THEN a new authenticated identity is provisioned and mapped to a `users` row

#### Scenario: Returning Google sign-in resolves the existing account

- GIVEN a user previously signed in with Google
- WHEN they sign in with Google again
- THEN the system resolves the same `users` identity, not a duplicate

### Requirement: Google Login Is Independent From Google Calendar OAuth

Signing in with Google (authentication) MUST be a separate integration from the `CalendarSyncPort` OAuth connection (calendar access): distinct scopes, distinct token stores, distinct consent screens. Neither MUST imply or require the other.

#### Scenario: Google login without granting Calendar access

- GIVEN a patient signs in using "Sign in with Google"
- WHEN they complete login
- THEN the system MUST NOT have obtained or stored any Google Calendar access — Calendar sync remains disconnected until the patient separately completes the `CalendarSyncPort` OAuth flow

#### Scenario: Calendar connection does not require Google login

- GIVEN a patient authenticated via email+password (not Google)
- WHEN they connect Google Calendar via `CalendarSyncPort`
- THEN the connection MUST succeed independently of their login method — there is no requirement to also authenticate with Google

### Requirement: No Plaintext Credential Storage in Kureha

Kureha MUST NOT persist plaintext passwords or unencrypted long-lived authentication secrets in its own database, regardless of whether credentials are validated locally or delegated to an external identity provider.

#### Scenario: Credential storage audited

- GIVEN a review of the users/credentials storage layer
- WHEN inspected directly
- THEN no plaintext password or raw federated-login secret MUST be recoverable from stored data

### Requirement: Authenticated Identity Maps to Authorization Context

After successful authentication (password or federated), the system MUST resolve the identity to a `users` row establishing `tenant_id`, `site_id`, and `role` before any authorization-scoped operation is permitted. An authenticated identity with no resolvable mapping MUST be denied access, not granted a default role.

#### Scenario: Unmapped identity is denied

- GIVEN a token or session proves successful authentication
- WHEN no corresponding `users` row exists (identity not provisioned/linked)
- THEN the request MUST be denied and the attempt MUST be audited

### Requirement: Email Verification for Account Linking

An account created via email+password signup MUST verify the email before granting full access. A Google-authenticated email is considered pre-verified by the identity provider, but linking it to an existing password-based account MUST require explicit confirmation — accounts MUST NOT silently merge on email match alone.

#### Scenario: Unverified email blocks full access

- GIVEN a new password-signup with an unverified email
- WHEN the user attempts an action requiring a verified identity
- THEN the system MUST require verification first

#### Scenario: Google email matches an existing password account

- GIVEN a patient has an existing password-based account with email `a@example.com`
- WHEN they sign in with Google using the same email for the first time
- THEN the system MUST require explicit confirmation before linking the Google identity to the existing account — it MUST NOT auto-merge silently
