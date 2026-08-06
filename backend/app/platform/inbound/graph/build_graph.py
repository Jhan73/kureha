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
    """LLM/calendar seam ports for `build_graph()`; defaults are Unwired* placeholders."""

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
    """Routes after confirmation: response_guard | hitl_approval | persist_and_audit.

    Re-reads ActionRiskPort here (LangGraph edges cannot call node internals)."""

    async def route_after_confirmation(state: KurehaState) -> str:
        if state.get("confirmation") not in ("not_required", "affirmed"):
            return "response_guard"

        proposed_action = state.get("proposed_action")
        if proposed_action is None:
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
    """RLS: calendar_credentials_self requires app.role='patient' for this read."""
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
    """Compile the request-scoped graph on the RLS-scoped `conn` + checkpointer."""
    deps = deps or GraphDependencies()

    # Fresh PermissionService per request (never a singleton); shared by rbac_gate + resolve_toolset.
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
