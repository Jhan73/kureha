# Patient Self-Service Portal Specification (patient-self-service-portal)

## Purpose

Patient manages their own appointments via traditional web forms. The portal is an inbound adapter over the same domain use cases as any other channel (see `appointment-scheduling`'s channel-agnostic requirement) — it MUST NOT implement parallel or divergent business rules.

## Requirements

### Requirement: Web Form Channel for Patient Self-Service

An authenticated patient MUST be able to create, reschedule, and cancel their own appointments via web forms, subject to the same RLS, consent, and RBAC rules as any other channel.

#### Scenario: Patient books via form

- GIVEN an authenticated patient with valid consent
- WHEN they submit a new-appointment form for an available slot
- THEN the appointment is created and confirmed, identically to a chat- or staff-originated booking

#### Scenario: Cross-patient access attempt via form

- GIVEN an authenticated patient
- WHEN they submit a form referencing another patient's appointment id (e.g. via tampered form field)
- THEN the request MUST be denied by RLS
- AND the attempt MUST be audited

### Requirement: Consent Gate Enforced in Portal

Before submitting any data-touching form, the portal MUST verify the patient has active consent per `versioned-consent`.

#### Scenario: Pending consent blocks form submission

- GIVEN a patient without an accepted current-version consent
- WHEN they attempt to submit an appointment form
- THEN the system MUST block submission and redirect to the consent flow

### Requirement: Portal Has No Channel-Specific Bypass Logic

The portal MUST read and write exclusively through the same use cases as other channels; it MUST NOT contain scheduling, cancellation, or availability logic duplicated or diverging from the shared domain layer.

#### Scenario: Consistent state across channels

- GIVEN an appointment created via the portal
- WHEN it is later viewed via the embedded chat or by staff
- THEN it MUST appear identically, with the same audit trail shape, regardless of originating channel