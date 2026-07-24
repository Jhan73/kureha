"""`build_graph()` (design.md §8.2/§8.3/§8.6, tasks.md task 11.6): wires
every node from batches 1-3 (17 nodes total: 8 from batch 1, 2 from batch 2,
7 from this batch) plus `route_from_start` into ONE compiled
`StateGraph(KurehaState)`, exactly per design.md §8.3's edge diagram.

**Deliberate construction-time choice, documented not guessed (per this
task's own instruction): a FRESH graph is compiled PER REQUEST, not once at
app startup.** `app/main.py`'s existing singletons (`app.db.engine`/
`runtime_engine`, `app.state.http_client`) are all STATELESS resource
FACTORIES/POOLS -- any number of concurrent callers can safely check out
their own connection/request from them. A compiled `StateGraph`, by
contrast, is compiled WITH a fixed set of node closures already bound to
whichever `AsyncConnection`/ports they close over (`persist_and_audit`/
`calendar_sync` need the SAME already-RLS-scoped `conn` every other router
uses for this specific request, exactly like `build_schedule_appointment
(conn)` in `routers/scheduling.py`) -- a graph compiled ONCE at startup
could not later be handed a DIFFERENT request's connection without either
(a) smuggling it through `KurehaState` (rejected -- this whole package's
established precedent, batch 1's own docstring: "state carries data only,
never collaborators") or (b) a second per-node-call indirection layer this
batch does not need to invent. Compiling a `StateGraph` is CHEAP, pure
in-process wiring (no I/O -- `add_node`/`add_edge`/`add_conditional_edges`
are all synchronous dict/graph-structure mutations; `checkpointer=...` is
the only thing that touches Postgres, and callers already own that
resource's lifetime) -- unlike opening a DB connection, so "compile once vs
per request" is a non-issue for latency/cost; the constraint that actually
forces this choice is connection OWNERSHIP/lifetime, not performance.
`build_graph()` is therefore called once per request by task 11.7's chat
endpoint, the same way `build_schedule_appointment(conn)` and every other
`build_*` composition-root factory already is.

**`AsyncPostgresSaver.setup()` is deliberately NOT called here or anywhere
in this batch.** Migration `043b5dd9768e` already ran the (sync twin)
`PostgresSaver.setup()` against this same DDL (`langgraph.checkpoint.
postgres.base.MIGRATIONS`, shared by both the sync and async savers) AND
already enabled+forced RLS with the `thread_id`-tenant-prefix policy on
`checkpoints`/`checkpoint_writes`/`checkpoint_blobs` (see that migration's
own docstring for why it used the sync saver, not the async one, from
inside Alembic). Calling `.setup()` again at request or startup time would
just re-run the SAME idempotent internal migration-tracking check
(`checkpoint_migrations`) for no benefit -- the schema is already correct
and already RLS-enforced from the migration itself.

**FLAGGED, unresolved gap: RLS on `checkpoints`/`checkpoint_writes`/
`checkpoint_blobs` requires `current_setting('app.tenant_id')` to be SET on
whichever physical connection the checkpointer uses for its own
reads/writes -- this module does not set it.** `langgraph-checkpoint-
postgres` requires a `psycopg` (not `asyncpg`) connection/pool, a
COMPLETELY SEPARATE physical connection from the SQLAlchemy `conn` this
module's other nodes share (that one goes through `asyncpg`, per
`app.db`'s own docstring) -- there is no shared transaction between the
two, and nothing in `langgraph-checkpoint-postgres` itself knows to run a
tenant-scoped `SET LOCAL app.tenant_id` before its own internal
`SELECT`/`INSERT` statements against those three tables. Task 11.7's chat
endpoint (the only real caller of `build_graph()` today) is responsible for
handing this function an ALREADY-tenant-scoped checkpointer connection --
see that router's own module docstring for exactly how it does this
(`SET LOCAL app.tenant_id` on the checkpointer's dedicated psycopg
connection, mirroring `session_context.py`'s GUC-setting convention, before
constructing `AsyncPostgresSaver`). This module accepts `checkpointer` as
an already-constructed collaborator specifically so it never has to make
that decision itself -- but the decision is real, and worth a dedicated
follow-up: a checkpointer backed by a genuinely POOLED psycopg connection
(reused across many requests/tenants over its lifetime, unlike this
per-request-scoped approach) would need a `configure`/per-checkout GUC-reset
mechanism this codebase does not have yet."""

from dataclasses import dataclass, field
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncConnection

from app.composition_root import build_permission_service
from app.modules.governance.rbac.application.use_cases.authorize_action import AuthorizeAction
from app.modules.calendar.adapters.outbound.postgres.calendar_credential_repository import (
    PostgresCalendarCredentialRepository,
)
from app.modules.calendar.application.ports.driven.calendar_sync import CalendarSyncPort
from app.modules.calendar.application.ports.driven.credential_vault import CredentialVaultPort
from app.modules.governance.audit.adapters.outbound.postgres.audit_log import PostgresAuditLog
from app.modules.governance.audit.application.ports.driven.audit_log import AuditLogPort
from app.modules.governance.consent.adapters.outbound.postgres.consent_registry import PostgresConsentRegistry
from app.modules.governance.consent.application.use_cases.check_consent import CheckConsent
from app.modules.governance.rbac.adapters.outbound.rbac.action_risk_reader import ActionRiskReader
from app.modules.governance.rbac.application.ports.driven.action_risk import ActionRiskPort
from app.modules.governance.rbac.application.use_cases.list_allowed_actions import ListAllowedActions
from app.modules.governance.scope.adapters.outbound.unwired.unwired_scope_policy import UnwiredClinicalScopePolicy
from app.modules.governance.scope.domain.scope_policy import ClinicalScopePolicy
from app.platform.inbound.api.access_control.role_scope import scoped_as_patient
from app.platform.inbound.graph.adapters.unwired import (
    UnwiredAffirmationClassifier,
    UnwiredDirectResponse,
    UnwiredIntentClassifier,
    UnwiredReminderPlanner,
    UnwiredSchedulingPlanner,
    UnwiredStaffPlanner,
    UnwiredSuggestionGenerator,
)
from app.platform.inbound.graph.nodes.calendar_sync import make_calendar_sync_node
from app.platform.inbound.graph.nodes.clinical_scope_validator import make_clinical_scope_validator_node
from app.platform.inbound.graph.nodes.confirmation_gate import make_confirmation_gate_node
from app.platform.inbound.graph.nodes.consent_gate import make_consent_gate_node
from app.platform.inbound.graph.nodes.deny_action import make_deny_action_node
from app.platform.inbound.graph.nodes.direct_respond import make_direct_respond_node
from app.platform.inbound.graph.nodes.escalate_human import make_escalate_human_node
from app.platform.inbound.graph.nodes.hitl_approval import make_hitl_approval_node
from app.platform.inbound.graph.nodes.persist_and_audit import make_persist_and_audit_node
from app.platform.inbound.graph.nodes.rbac_gate import make_rbac_gate_node
from app.platform.inbound.graph.nodes.reminders_agent import make_reminders_agent_node
from app.platform.inbound.graph.nodes.resolve_toolset import make_resolve_toolset_node
from app.platform.inbound.graph.nodes.respond import make_respond_node
from app.platform.inbound.graph.nodes.response_guard import make_response_guard_node
from app.platform.inbound.graph.nodes.scheduling_agent import build_scheduling_agent_node
from app.platform.inbound.graph.nodes.staff_agent import make_staff_agent_node
from app.platform.inbound.graph.nodes.triage import make_triage_node
from app.platform.inbound.graph.ports.affirmation_classifier import AffirmationClassifierPort
from app.platform.inbound.graph.ports.direct_response import DirectResponsePort
from app.platform.inbound.graph.ports.intent_classifier import IntentClassifierPort
from app.platform.inbound.graph.ports.reminder_planner import ReminderPlannerPort
from app.platform.inbound.graph.ports.scheduling_planner import SchedulingPlannerPort
from app.platform.inbound.graph.ports.staff_planner import StaffPlannerPort
from app.platform.inbound.graph.ports.suggestion_generator import SuggestionGeneratorPort
from app.platform.inbound.graph.state import KurehaState

_LIGHT_INTENTS = frozenset({"greeting", "capability_query", "small_talk"})
_SCHEDULING_INTENTS = frozenset({"schedule", "reschedule", "cancel"})
_STAFF_INTENTS = frozenset({"staff", "shift"})


@dataclass
class GraphDependencies:
    """Every LLM-shaped seam port `build_graph()` needs, defaulted to the
    `Unwired*` placeholders (`adapters/unwired.py`'s own module docstring)
    since no real LLM adapter exists anywhere in this codebase yet (tasks.md
    Phase 12's job) -- a caller (task 11.7's chat endpoint today) overrides
    whichever ones a later phase wires for real, without every OTHER field
    needing to change. `calendar_sync_port`/`credential_vault` default to
    `None` -- harmless as long as no turn ever reaches `calendar_sync` with
    them unset (the `Unwired*` classifiers/planners raise long before that
    could happen for a real conversational turn; a `web_form` schedule with
    a genuinely connected calendar is the one path that WOULD need them
    real)."""

    intent_classifier: IntentClassifierPort = field(default_factory=UnwiredIntentClassifier)
    scheduling_planner: SchedulingPlannerPort = field(default_factory=UnwiredSchedulingPlanner)
    reminder_planner: ReminderPlannerPort = field(default_factory=UnwiredReminderPlanner)
    staff_planner: StaffPlannerPort = field(default_factory=UnwiredStaffPlanner)
    affirmation_classifier: AffirmationClassifierPort = field(default_factory=UnwiredAffirmationClassifier)
    direct_response: DirectResponsePort = field(default_factory=UnwiredDirectResponse)
    suggestion_generator: SuggestionGeneratorPort = field(default_factory=UnwiredSuggestionGenerator)
    scope_policy: ClinicalScopePolicy = field(default_factory=UnwiredClinicalScopePolicy)
    calendar_sync_port: CalendarSyncPort | None = None
    credential_vault: CredentialVaultPort | None = None


def _route_from_start(state: KurehaState) -> str:
    """design.md §8.2's own literal shape: `graph.add_conditional_edges(
    START, lambda s: "confirmation_gate" if s.get("proposed_action") else
    "triage")`."""
    return "confirmation_gate" if state.get("proposed_action") else "triage"


def _route_from_triage(state: KurehaState) -> str:
    return "direct_respond" if state.get("intent") in _LIGHT_INTENTS else "clinical_scope_validator"


def _route_by_scope(state: KurehaState) -> str:
    return "consent_gate" if state.get("scope_ok") else "escalate_human"


def _route_by_consent(state: KurehaState) -> str:
    return "resolve_toolset" if state.get("consent_ok") else "escalate_human"


def _route_by_intent(state: KurehaState) -> str:
    intent = state.get("intent")
    if intent in _SCHEDULING_INTENTS:
        return "scheduling_agent"
    if intent == "reminder":
        return "reminders_agent"
    if intent in _STAFF_INTENTS:
        return "staff_agent"
    return "escalate_human"  # unknown


def _route_by_rbac(state: KurehaState) -> str:
    return "confirmation_gate" if state.get("rbac_ok") else "deny_action"


def _make_route_after_confirmation(action_risk: ActionRiskPort):
    """Merges design.md §8.3's `confirmation_gate`'s three-way branch WITH
    `route_by_risk` into one conditional-edge function -- LangGraph routes
    to actual NODE names, not to another router, so `route_by_risk` cannot
    be a separate hop the way design.md's prose names it. Reads
    `ActionRiskPort` live, itself -- `hitl_approval` (batch 2) already
    independently re-derives `requires_hitl` internally for audit-payload
    purposes, but a conditional edge function cannot call a node's
    internals to make its OWN routing decision (this task's own
    instruction), so this is the SAME port, a SECOND live read, by
    design."""

    async def route_after_confirmation(state: KurehaState) -> str:
        if state.get("confirmation") not in ("not_required", "affirmed"):
            # "needed" (Caso B, first ask) or None (Caso C decline) --
            # both terminate the turn via response_guard -> respond -> END.
            return "response_guard"

        proposed_action = state.get("proposed_action")
        if proposed_action is None:
            # Structurally unreachable (both entry edges into
            # confirmation_gate only fire with a proposed_action) --
            # guarded defensively, matching every other node's own posture.
            return "persist_and_audit"

        if state.get("risk_level") == "high":
            return "hitl_approval"

        risk_config = await action_risk.get(proposed_action.action)
        return "hitl_approval" if risk_config.requires_hitl else "persist_and_audit"

    return route_after_confirmation


def _route_by_approval(state: KurehaState) -> str:
    approval = state.get("approval")
    return "persist_and_audit" if approval is not None and approval.approved else "escalate_human"


async def _patient_has_connected_calendar(conn: AsyncConnection, ctx, patient_id: str) -> bool:
    """Re-scopes `conn` to `app.role='patient'` for the duration of this
    ONE read (`role_scope.py`'s `scoped_as_patient`, the SAME mechanism
    `build_sync_appointment_to_calendar` uses for the dual-role RLS gap) --
    `calendar_credentials`' only RLS policy (`calendar_credentials_self`)
    requires it regardless of whether the CALLING actor is staff or the
    patient themselves."""
    credential_repository = PostgresCalendarCredentialRepository(conn)
    async with scoped_as_patient(conn, patient_id=patient_id, restore_role=ctx.role):
        credential = await credential_repository.get(ctx.tenant_id, patient_id)
    return credential is not None and not credential.is_revoked


def _make_route_after_persist(conn: AsyncConnection):
    async def route_after_persist(state: KurehaState) -> str:
        if state.get("intent") not in _SCHEDULING_INTENTS:
            return "response_guard"

        ctx = state["request_ctx"]
        proposed_action = state.get("proposed_action")
        patient_id = ctx.patient_id
        if patient_id is None and proposed_action is not None:
            patient_id = proposed_action.payload.get("patient_id")
        if patient_id is None:
            return "response_guard"

        has_calendar = await _patient_has_connected_calendar(conn, ctx, patient_id)
        return "calendar_sync" if has_calendar else "response_guard"

    return route_after_persist


def _route_by_response_scope(state: KurehaState) -> str:
    return "respond" if state.get("response_scope_ok") else "escalate_human"


async def build_graph(
    conn: AsyncConnection, *, checkpointer: BaseCheckpointSaver, deps: GraphDependencies | None = None
) -> Any:
    """Compiles the FULL 17-node graph (design.md §8.2/§8.3) for ONE
    request, bound to `conn` (the SAME already-RLS-scoped connection every
    other router in this codebase uses, e.g. `get_db_conn`/
    `build_schedule_appointment(conn)`) and `checkpointer` (see this
    module's own docstring for the deliberate choice of NOT constructing
    one here). `deps` defaults to every seam port's `Unwired*` placeholder
    -- see `GraphDependencies`'s own docstring."""
    deps = deps or GraphDependencies()

    # ONE fresh `PermissionService` for this request (design.md §5.6/ADR-16
    # -- see `build_permission_service`'s own docstring: never a singleton),
    # shared by `AuthorizeAction` (`rbac_gate`) and `ListAllowedActions`
    # (`resolve_toolset`) -- both need the SAME `AuthorizationPort` a real
    # request's memo would otherwise duplicate for no reason.
    permission_service = build_permission_service(conn)
    authorize_action = AuthorizeAction(permission_service)
    list_allowed_actions = ListAllowedActions(permission_service)
    check_consent = CheckConsent(PostgresConsentRegistry(conn))
    audit_log: AuditLogPort = PostgresAuditLog(conn)
    action_risk: ActionRiskPort = ActionRiskReader(conn)

    graph = StateGraph(KurehaState)

    graph.add_node("triage", make_triage_node(deps.intent_classifier))
    graph.add_node("clinical_scope_validator", make_clinical_scope_validator_node(deps.scope_policy))
    graph.add_node("consent_gate", make_consent_gate_node(check_consent))
    graph.add_node("resolve_toolset", make_resolve_toolset_node(list_allowed_actions))
    graph.add_node("scheduling_agent", await build_scheduling_agent_node(deps.scheduling_planner, action_risk))
    graph.add_node("reminders_agent", make_reminders_agent_node(deps.reminder_planner))
    graph.add_node("staff_agent", make_staff_agent_node(deps.staff_planner))
    graph.add_node("rbac_gate", make_rbac_gate_node(authorize_action))
    graph.add_node("confirmation_gate", make_confirmation_gate_node(deps.affirmation_classifier))
    graph.add_node("hitl_approval", make_hitl_approval_node(action_risk, audit_log))
    graph.add_node("persist_and_audit", make_persist_and_audit_node(conn))
    graph.add_node(
        "calendar_sync",
        make_calendar_sync_node(conn, calendar_sync_port=deps.calendar_sync_port, credential_vault=deps.credential_vault),
    )
    graph.add_node("response_guard", make_response_guard_node(deps.scope_policy))
    graph.add_node("direct_respond", make_direct_respond_node(deps.direct_response))
    graph.add_node("escalate_human", make_escalate_human_node(audit_log))
    graph.add_node("deny_action", make_deny_action_node(audit_log))
    graph.add_node("respond", make_respond_node(deps.suggestion_generator))

    graph.add_conditional_edges(START, _route_from_start, ["confirmation_gate", "triage"])
    graph.add_conditional_edges("triage", _route_from_triage, ["direct_respond", "clinical_scope_validator"])
    graph.add_edge("direct_respond", "response_guard")
    graph.add_conditional_edges("clinical_scope_validator", _route_by_scope, ["consent_gate", "escalate_human"])
    graph.add_conditional_edges("consent_gate", _route_by_consent, ["resolve_toolset", "escalate_human"])
    graph.add_conditional_edges(
        "resolve_toolset", _route_by_intent, ["scheduling_agent", "reminders_agent", "staff_agent", "escalate_human"]
    )
    graph.add_edge("scheduling_agent", "rbac_gate")
    graph.add_edge("reminders_agent", "rbac_gate")
    graph.add_edge("staff_agent", "rbac_gate")
    graph.add_conditional_edges("rbac_gate", _route_by_rbac, ["confirmation_gate", "deny_action"])
    graph.add_conditional_edges(
        "confirmation_gate",
        _make_route_after_confirmation(action_risk),
        ["response_guard", "hitl_approval", "persist_and_audit"],
    )
    graph.add_conditional_edges("hitl_approval", _route_by_approval, ["persist_and_audit", "escalate_human"])
    graph.add_conditional_edges(
        "persist_and_audit", _make_route_after_persist(conn), ["calendar_sync", "response_guard"]
    )
    graph.add_edge("calendar_sync", "response_guard")
    graph.add_conditional_edges("response_guard", _route_by_response_scope, ["respond", "escalate_human"])
    graph.add_edge("escalate_human", "respond")
    graph.add_edge("deny_action", "respond")
    graph.add_edge("respond", END)

    return graph.compile(checkpointer=checkpointer)
