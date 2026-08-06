## Backend Standards

* Python 3.13+, managed with `uv` (use `uv add`/`uv run`, don't hand-edit `pyproject.toml` deps if `uv` is available).
* FastAPI for the inbound API. SQLAlchemy **Core**, not the ORM — RLS and fine-grained transaction control (`SET LOCAL`, audit writes in the same tx) are expressed directly in SQL.
* Alembic for migrations. Every migration must be reversible (`downgrade()` implemented, not `pass`).
* LangGraph for agent orchestration (`AsyncPostgresSaver` checkpointer). LangGraph is runtime, not domain — no business rule lives inside a node.

### Architecture: Hexagonal (Ports & Adapters) over a Modular Monolith

* One process, one deploy unit — not microservices. Each module is a full hexagon (`domain -> application -> adapters`), all sharing the same Postgres connection.
* Dependency direction is one-way and enforced by `import-linter`:
  `platform -> business modules -> governance modules -> shared_kernel`.
* Business modules (`tenancy`, `identity`, `scheduling`, `staff`, `calendar`) **never** import another business module's internals. If `staff` needs something from `scheduling`, that goes through `platform/inbound/graph/` orchestration, not a direct import.
* Governance modules (`governance/consent`, `governance/audit`, `governance/scope`, `governance/rbac`) are cross-cutting: any business module may depend on their public ports, but governance never depends on a business module — it only knows generic concepts (`ActionKey`, `TenantContext`), never `Appointment` or `Shift`.
* `shared_kernel/` is value objects only — `TenantContext`, `DomainError`, `ClockPort`, `IdGeneratorPort`. No IO, no business logic. Don't add anything here that isn't a pure type.
* `platform/` (inbound API, channels, LangGraph graph) orchestrates across modules by calling their public use cases. Nothing inside `modules/` may import from `platform/`.
* One `composition_root.py` is the only place allowed to know about every module at once and wire adapters into use cases.

Before adding a new dependency between modules, check `openspec/changes/kureha-mvp/design.md` §2.4 — if it violates the layering, the `import-linter` contracts in `pyproject.toml` will fail CI, and that's the point.

### Multi-tenancy & RLS

* Every operational table carries `tenant_id` (and usually `site_id`) with **RLS `ENABLE` + `FORCE`**, deny-by-default. Session-scoped GUCs (`SET LOCAL app.tenant_id`, etc.) carry the request context — never filter by tenant in application code as a substitute for a policy.
* RBAC (action-based permissions) is a *second*, independent authorization plane on top of RLS — it narrows what a role can *do*, RLS narrows what rows exist. Neither one substitutes for the other.

### Testing

* No strict TDD yet (`openspec/config.yaml` → `strict_tdd: false`) — the test runner (pytest + pytest-asyncio) was only introduced in PR 1 of `kureha-mvp`. Re-evaluate once real domain modules start shipping.
* RLS and RBAC tests must assert **zero rows** / **deny**, not just "doesn't crash" — see `design.md` §14 for the full layer-by-layer testing guide (RLS isolation, RBAC∩RLS intersection, consent states, scope guardrails, HITL pause/resume, confirmation gate, calendar-sync failure isolation, hash-chain audit, rate-counter cleanup).
* Run `uv run pytest`, `uv run lint-imports` (import-linter contracts) before considering a task done.
* Run `uv run basedpyright app tests` and treat `reportDeprecated` warnings as must-fix (configured in `pyrightconfig.json` / `[tool.basedpyright]`).
* **`tests/platform/inbound/api/routers`'s full-app router tests genuinely COMMIT data** (real `TestClient` + the app's own pooled engine, not `tests/conftest.py`'s per-test rollback pattern — see that package's `conftest.py` module docstring for why no dependency-injectable seam allows rollback-per-test there). Two consequences for any OTHER test sharing the same Postgres database in the same `pytest` session: (1) never bare-insert (no `ON CONFLICT`) a literal, real `ACTION_CATALOG`/business key into a global, non-tenant-scoped table (`action_permissions`) — use a permanently-reserved, obviously-fictional probe key instead (e.g. `test_probe:never_real`, see `tests/schema/test_rbac_tables.py`), never a merely-not-yet-seeded real key, since that becomes a real collision the moment the catalog grows; (2) never assert on an unscoped read of a shared table's full contents (e.g. `SELECT * FROM rate_counters`) — scope reads to rows/subjects your own test created, since an unscoped read implicitly depends on every other test file's cleanup having already run, which is not guaranteed under a different execution order (`pytest-randomly`, `pytest-xdist`, a partial test-path run).

### Conventions

* Code, identifiers, comments, docstrings, and error messages: **English**. SDD documentation (`openspec/`) stays in Spanish — don't mix the two.
* Follow the folder layout in `openspec/changes/kureha-mvp/design.md` §2.5 exactly (`app/shared_kernel/`, `app/modules/<name>/{domain,application,adapters}/`, `app/platform/{inbound,outbound}/`) — don't invent new top-level folders without updating that design doc first.
* Comments/docstrings: minimal. Never cite `tasks.md`, specs, `design.md`, ADRs, or PR/work-unit history in code. Docstrings only for non-obvious params, agent-relevant constraints, or behavior the name does not already say — no narrative essays.
