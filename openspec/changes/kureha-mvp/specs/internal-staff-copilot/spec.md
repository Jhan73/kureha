# Internal Staff Copilot Specification (internal-staff-copilot)

## Purpose

The same chat engine used for the patient-facing channel, offered to authenticated staff. The toolset/actions exposed MUST be derived from the authenticated user's `action-based-rbac` permissions — an action not granted MUST NOT be offered, and MUST NOT be executable even if requested directly, at the domain layer, not only the UI layer.

## Requirements

### Requirement: Toolset Derived From Permissions

The copilot MUST only offer, as available tools/actions, those the authenticated staff user holds permission for per `action-based-rbac`. An unpermitted action MUST NOT appear as an offered capability.

#### Scenario: Unpermitted action not offered

- GIVEN a `reception` user lacks the `appointment:cancel` permission at their tenant
- WHEN they interact with the copilot
- THEN `appointment:cancel` MUST NOT appear among the tools the copilot can invoke for that session

#### Scenario: Free-text request for unpermitted action is declined, not attempted

- GIVEN the same `reception` user types a free-text request to cancel an appointment
- WHEN the copilot processes it
- THEN it MUST decline and explain the action is not available to them, without attempting the underlying use case

### Requirement: Domain-Layer Enforcement, Not UI-Only

Even if a tool invocation for an unpermitted action is attempted (e.g. a crafted request bypassing the copilot's own tool-selection step), the underlying use-case layer MUST independently re-check the permission and deny it. Hiding a tool from the copilot's offered set MUST NOT be the only enforcement point.

#### Scenario: Direct invocation attempt denied at domain layer

- GIVEN a `reception` user lacks permission for an admin-only action
- WHEN a request reaches the underlying use case directly (bypassing the copilot's tool-offer step)
- THEN the use case MUST deny it with the same outcome as `action-based-rbac`'s direct-API-call scenario
- AND the denial MUST be audited

### Requirement: Copilot Respects RLS Regardless of RBAC

The copilot MUST operate under the authenticated staff user's `tenant_id`/`site_id`/role RLS context for every tool call. An RBAC permission grant MUST NOT surface data outside that RLS scope.

#### Scenario: Permitted action, out-of-scope data

- GIVEN a staff user holds the `appointment:view` action permission
- WHEN they ask the copilot for an appointment at a sede outside their session scope
- THEN RLS MUST deny the row regardless of the action permission, consistent with `role-based-rls`

### Requirement: Same Clinical Scope Guardrail Applies Internally

The copilot MUST NOT provide diagnosis or clinical interpretation to staff either. It MAY provide administrative orientation (e.g. summarizing schedule conflicts, next administrative steps).

#### Scenario: Staff asks for clinical interpretation

- GIVEN a staff user asks the copilot to interpret a patient's described symptoms to prioritize triage order
- WHEN the copilot responds
- THEN it MUST decline the clinical interpretation and defer to professional judgment, per `clinical-scope-validator`
- AND MAY still help with administrative triage ordering that does not require symptom interpretation

### Requirement: Streaming Responses With Intermediate Status Visibility

Copilot responses MUST stream incrementally to the client as they are generated, and intermediate status/events (e.g. a tool call in progress) MUST be surfaced to the staff user during generation, consistent with `embedded-patient-chat`'s streaming requirement. Status/events MUST NOT reveal the name of a tool, or any partial result, that the authenticated staff user does not hold permission for per `action-based-rbac` — including transiently during streaming, before the final response is assembled.

#### Scenario: Streaming status shows only permitted tool activity

- GIVEN a `reception` user without `appointment:cancel` permission is chatting with the copilot
- WHEN the copilot streams its response
- THEN no intermediate status event MUST reference `appointment:cancel` or any tool the user lacks permission for, even if the underlying reasoning considered and rejected it

#### Scenario: Partial tool result not leaked before authorization check

- GIVEN a copilot response would eventually reference data protected by RLS or RBAC that the user does not have access to
- WHEN the response streams
- THEN no partial token or status event before the final answer MUST expose that unauthorized data — the same enforcement that applies to the final response applies to every intermediate chunk

### Requirement: Confirmation Required Before Any Mutating Action

Before executing any create, update, or delete operation reached via a copilot-derived intent, the copilot MUST present the intended action back to the staff user in plain language — what will be created, updated, or deleted, plus the key details (e.g. "I'm going to reschedule this appointment to [date] at [time] with Dr. X, confirm?") — and MUST obtain explicit affirmative confirmation before executing it. This applies to any permitted mutating action (per `action-based-rbac`), regardless of whether it also happens to trigger one of the narrower high-risk approvals in `clinical-safety`'s Human-in-the-Loop requirement (bulk cancellation, professional-reassignment mismatch, or a tenant-configured action requiring approval) — it is a channel-level baseline layered on top of, not a substitute for, those triggers. Unlike that Human-in-the-Loop flow, which pauses execution via an interrupt-equivalent checkpoint and routes to a separate staff approver, this confirmation is a lightweight, conversational exchange resolved directly with the requesting staff user, in the same turn or the immediately following turn — it does NOT pause for a separate approver. A read-only action (e.g. checking a schedule, looking up an existing appointment) MUST NOT require this confirmation step.

#### Scenario: Single ordinary mutation still requires confirmation

- GIVEN a staff user with the `appointment:reschedule` permission asks the copilot to reschedule an appointment with the originally-booked professional (not a bulk cancellation, not a reassignment mismatch, not a tenant-configured HITL action)
- WHEN the copilot has resolved a specific target slot
- THEN it MUST restate the intended change in plain language and ask for explicit confirmation before executing it
- AND this MUST happen even though the action does not meet any narrower HITL trigger and is not routed to a staff approver

#### Scenario: Staff user declines the proposed action

- GIVEN the copilot has presented an intended mutating action and asked for confirmation
- WHEN the staff user responds negatively or does not affirm
- THEN the action MUST NOT execute — no record MUST be created, updated, or deleted
- AND the copilot MUST acknowledge the cancellation cleanly and offer to continue with a different request

#### Scenario: Read-only lookup does not require confirmation

- GIVEN a staff user asks the copilot to check a day's schedule or look up an existing appointment
- WHEN the copilot processes the request
- THEN it MUST answer directly without asking for confirmation, since no state-changing operation is involved

#### Scenario: Confirmation prompt composes with streaming

- GIVEN the copilot is about to propose a mutating action
- WHEN it streams its response per the Streaming Responses requirement
- THEN the confirmation prompt itself MUST be delivered as part of that streamed response
- AND the action MUST only execute after the staff user's next turn affirms it — this turn-boundary confirmation is a distinct mechanism from the graph-level Human-in-the-Loop interrupt used for bulk-cancel and reassignment-mismatch

### Requirement: Markdown-Formatted Responses

Copilot responses MUST be formatted as Markdown, for the same legibility reasons as `embedded-patient-chat`.

#### Scenario: Staff copilot renders a schedule summary as Markdown

- GIVEN the copilot summarizes a day's schedule conflicts for a staff user
- WHEN it responds
- THEN the response MUST use Markdown formatting (e.g. a list or table) rather than unformatted text