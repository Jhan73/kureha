# Kureha

Multi-tenant operations platform for clinics and medical practices in Peru: scheduling, patient self-service (web + embedded chat), Google Calendar sync, staff operations, and an internal staff copilot — all built on a governance core (RLS, versioned consent, append-only audit, mandatory human-in-the-loop, clinical-scope guardrails).

## Repo layout

* `backend/` — Python 3.13 hexagonal monolith. See `backend/AGENTS.md`.
* `frontend/` — Next.js SPA (static export). See `frontend/AGENTS.md`.
* `infra/` — local dev infra (LocalStack, Postgres init scripts) consumed by `docker-compose.yml`.
* `openspec/` — Spec-Driven Development source of truth: `config.yaml` (stack, conventions, regulatory constraints), `changes/kureha-mvp/` (proposal, specs, design, tasks for the current MVP build), `specs/` (accumulated specs once changes archive).

`openspec/config.yaml` is authoritative for stack decisions, phase rules, and non-negotiable regulatory context (Ley 29733, RENHICE/HL7 FHIR PE-CORE, Reglamento Ley 31814, SUSALUD). Read it before assuming anything about scope or constraints — don't re-derive that context from scratch in a proposal or PR.

## Conventions

* Code, identifiers, comments, and error messages: English, everywhere in `backend/` and `frontend/`.
* SDD documentation under `openspec/` (proposal/spec/design/tasks): Spanish, matching the rest of the project's planning trail.
* This is a monorepo but `backend/` and `frontend/` are independently deployable — don't add cross-directory imports or shared code outside of documented contracts (OpenAPI schema, not shared TS/Python packages).
* Comments and docstrings: minimal. Never cite `tasks.md`, specs, `design.md`, ADRs, PR numbers, or work-unit history in code. Keep a docstring only when it documents non-obvious parameters, agent-relevant constraints, or clarifies behavior the name does not already say — never essays or redundant restatements.

## Delivery

Work on `kureha-mvp` ships as chained PRs (see `openspec/changes/kureha-mvp/tasks.md` → "Suggested Work Units") on branches stacked off the `kureha-mvp` tracker branch, each scoped to one work unit. Don't bundle multiple work units into one PR without checking `tasks.md` first.
