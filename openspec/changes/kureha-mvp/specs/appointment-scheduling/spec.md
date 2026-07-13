# Appointment Scheduling Specification (appointment-scheduling, appointment-reminders)

## Purpose

Triage and specialist agents that schedule, reschedule, and cancel appointments within availability rules, plus reminders over an abstract channel port.

## Requirements

### Requirement: Intent Triage

The supervisor MUST classify each inbound message into one of: schedule, reschedule, cancel, reminder-related, or out-of-scope, before routing to a specialist agent.

#### Scenario: Message routed to scheduling

- GIVEN an inbound message requesting a new appointment
- WHEN the supervisor classifies it
- THEN it MUST route to `SchedulingAgent` with intent `schedule`

### Requirement: Channel-Agnostic Scheduling

`SchedulingAgent` MUST expose the same scheduling, reschedule, and cancel use cases regardless of the inbound channel (web form via `patient-self-service-portal`, embedded chat via `embedded-patient-chat`, or internal staff copilot via `internal-staff-copilot`). The channel is an inbound adapter only; it MUST NOT alter domain rules, RLS scope, consent checks, or HITL triggers.

#### Scenario: Identical outcome across channels

- GIVEN the same patient, slot, and intent
- WHEN the booking is submitted via the web form and, separately, via the embedded chat
- THEN both MUST produce an equivalent appointment record and an equivalent audit trail shape

#### Scenario: Cross-channel double-booking prevented

- GIVEN a slot is requested via the web form and, near-simultaneously, the same slot is requested via the embedded chat
- WHEN both are submitted at nearly the same time
- THEN only the first MUST succeed regardless of which channel it came from
- AND the second MUST fail with alternative-slot suggestions

### Requirement: Scheduling Within Availability Rules

`SchedulingAgent` MUST create, reschedule, or cancel appointments only within defined availability rules. It MUST NOT create overlapping appointments for the same professional and time slot.

#### Scenario: Happy-path booking

- GIVEN a requested slot within availability
- WHEN the patient confirms
- THEN the appointment is created and a confirmation is returned

#### Scenario: Double-booking prevented under concurrency

- GIVEN two concurrent requests for the same professional and slot
- WHEN both are submitted at nearly the same time
- THEN only the first MUST succeed
- AND the second MUST fail and receive alternative-slot suggestions, with no overlapping row ever committed

#### Scenario: Reschedule to unavailable slot rejected

- GIVEN a reschedule request targeting a slot outside availability
- WHEN it is submitted
- THEN it MUST be rejected and alternatives offered

### Requirement: Reminders and Confirmations

`RemindersAgent` SHOULD send confirmation and reminder messages through an abstract channel port ahead of the appointment, per a configurable lead time. Every delivery attempt MUST be logged to the audit trail.

#### Scenario: Reminder dispatched

- GIVEN an appointment inside the reminder lead-time window
- WHEN the lead time is reached
- THEN a reminder is dispatched via the channel port and the attempt is logged

#### Scenario: Channel port failure does not break scheduling

- GIVEN the channel port fails to deliver (no real connector in MVP)
- WHEN the delivery attempt fails
- THEN scheduling flows MUST NOT fail because of it
- AND the failure MUST be logged and retried per policy

#### Scenario: Patient replies to a reminder

- GIVEN a patient replies to a reminder to confirm or cancel
- WHEN the reply is received
- THEN it MUST be routed through triage like any inbound message, subject to the same RLS, consent, and HITL rules
