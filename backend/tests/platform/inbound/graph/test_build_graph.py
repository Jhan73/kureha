"""Task 11.6: `build_graph()` -- proves the COMPILED graph actually routes
end-to-end (not just each node in isolation, already covered by
`nodes/test_*.py`). Real Postgres (`rls_conn`, RLS-enforced) for every
governance/business use case `persist_and_audit`/`rbac_gate`/`consent_gate`/
`resolve_toolset` touch; fakes only for the LLM-shaped seam ports
(`IntentClassifierPort`/`SchedulingPlannerPort`/`ClinicalScopePolicy`/
`AffirmationClassifierPort`) -- no real LLM/adapter exists yet anywhere in
this codebase (see `adapters/unwired.py`'s own docstring).

Two scenarios, per this task's own instructions:
1. A representative LOW-RISK path (web_form schedule, `not_required`
   confirmation, no HITL) all the way to `persist_and_audit` -> `respond`.
2. The turn-N/turn-N+1 `confirmation_gate` round trip through the REAL
   compiled graph (not the node in isolation, already proven by batch 2's
   `test_confirmation_gate.py`) -- `MemorySaver` (batch 2's own precedent
   for `interrupt()` mechanics) stands in for `AsyncPostgresSaver` here;
   `build_graph()` accepts any `BaseCheckpointSaver`, and this package does
   not need a real Postgres-backed checkpointer to prove the EDGE WIRING
   itself is correct."""

from datetime import datetime, timezone

import sqlalchemy as sa
from langgraph.checkpoint.memory import MemorySaver

from app.composition_root import bootstrap_rbac_catalog_and_grants
from app.modules.governance.scope.domain.scope_policy import (
    InboundScopeCategory,
    InboundScopeResult,
    OutboundScopeCategory,
    OutboundScopeResult,
)
from app.platform.inbound.graph.build_graph import GraphDependencies, build_graph
from app.platform.inbound.graph.ports.affirmation_classifier import AffirmationResult
from app.platform.inbound.graph.ports.intent_classifier import IntentClassificationResult
from app.platform.inbound.graph.ports.scheduling_planner import SchedulingPlan
from app.platform.inbound.graph.state import KurehaState, RequestContext
from tests.rls.helpers import (
    seed_availability,
    seed_consent,
    seed_consent_policy,
    seed_patient,
    seed_professional,
    seed_site,
    seed_staff_member,
    seed_tenant,
    set_app_context,
)

_T0 = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
_T1 = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)


class _FakeIntentClassifier:
    def __init__(self, intent: str) -> None:
        self._intent = intent
        self.calls = 0

    async def classify(self, ctx, message: str) -> IntentClassificationResult:
        self.calls += 1
        return IntentClassificationResult(intent=self._intent)


class _FakeScopePolicy:
    async def classify_inbound(self, ctx, message: str) -> InboundScopeResult:
        return InboundScopeResult(category=InboundScopeCategory.IN_SCOPE, should_escalate=False)

    async def classify_outbound(self, ctx, chunk: str) -> OutboundScopeResult:
        return OutboundScopeResult(category=OutboundScopeCategory.SAFE, should_block=False)


class _FakeSchedulingPlanner:
    def __init__(self, *, action: str, kwargs: dict, summary: str) -> None:
        self._action = action
        self._kwargs = kwargs
        self._summary = summary

    async def plan(self, ctx, *, intent: str, message: str) -> SchedulingPlan:
        return SchedulingPlan(action=self._action, kwargs=self._kwargs, summary=self._summary)


class _SequencedAffirmationClassifier:
    """Content-based, not call-count-based -- a real classifier judges the
    MESSAGE, not which turn number it happens to be. Only an explicit
    affirmation word yields `"affirmed"`; anything else (the turn N
    original request, or an unrelated turn N+2 message) is `"unclear"` --
    `confirmation_gate`'s own incoming-checkpoint read (Part 0's fix) is
    what turns an "unclear" verdict into `"needed"` (fresh ask, turn N/N+2)
    vs a decline (turn N+1 reply that wasn't a clear yes)."""

    def __init__(self) -> None:
        self.calls = 0

    async def classify(self, ctx, message: str, *, pending_action_summary: str) -> AffirmationResult:
        self.calls += 1
        affirmed = any(word in message.lower() for word in ("confirmo", "sí", "si,", "sí,", "dale"))
        return AffirmationResult(decision="affirmed" if affirmed else "unclear")


async def _seed_schedulable_tenant(rls_conn):
    tenant_id = await seed_tenant(rls_conn)
    await bootstrap_rbac_catalog_and_grants(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    professional_id = await seed_professional(rls_conn, tenant_id, site_id)
    await seed_staff_member(
        rls_conn, tenant_id, site_id, operational_role="professional", professional_id=professional_id
    )
    patient_id = await seed_patient(rls_conn, tenant_id, site_id)
    await seed_consent_policy(rls_conn, tenant_id)
    await seed_consent(rls_conn, tenant_id, site_id, patient_id)
    availability_id = await seed_availability(rls_conn, tenant_id, site_id, professional_id, starts_at=_T0, ends_at=_T1)
    return {
        "tenant_id": tenant_id,
        "site_id": site_id,
        "professional_id": professional_id,
        "patient_id": patient_id,
        "availability_id": availability_id,
    }


def _initial_state(*, request_ctx: RequestContext, channel: str, channel_message: str) -> KurehaState:
    return {
        "request_ctx": request_ctx,
        "channel": channel,
        "channel_message": channel_message,
        "intent": None,
        "scope_ok": None,
        "consent_ok": None,
        "allowed_actions": None,
        "proposed_action": None,
        "rbac_ok": None,
        "risk_level": None,
        "confirmation": None,
        "approval": None,
        "outcome": None,
        "audit_ref": None,
        "response_text": None,
        "response_scope_ok": None,
        "calendar_sync_status": None,
        "suggestions": None,
    }


async def test_low_risk_web_form_schedule_routes_end_to_end_to_respond(rls_conn) -> None:
    seeded = await _seed_schedulable_tenant(rls_conn)
    user_id = "11111111-1111-1111-1111-111111111111"
    # `patient_id` is set directly here -- this test exercises the graph's
    # ROUTING/wiring, not `consent_gate`'s own already-flagged, unresolved
    # "staff_copilot on behalf of a different patient" positioning gap
    # (batch 1's docstring in `nodes/consent_gate.py`); a real turn resolving
    # WHICH patient a reception actor means is a separate, open question.
    request_ctx = RequestContext(
        tenant_id=seeded["tenant_id"],
        role="reception",
        site_id=seeded["site_id"],
        user_id=user_id,
        patient_id=seeded["patient_id"],
    )
    await set_app_context(rls_conn, tenant_id=seeded["tenant_id"], site_id=seeded["site_id"], role="reception", user_id=user_id)

    deps = GraphDependencies(
        intent_classifier=_FakeIntentClassifier("schedule"),
        scope_policy=_FakeScopePolicy(),
        scheduling_planner=_FakeSchedulingPlanner(
            action="appointment:create",
            kwargs={
                "patient_id": seeded["patient_id"],
                "professional_id": seeded["professional_id"],
                "site_id": seeded["site_id"],
                "availability_id": seeded["availability_id"],
            },
            summary="Cita agendada con el profesional el 2026-09-01 09:00",
        ),
    )
    graph = await build_graph(rls_conn, checkpointer=MemorySaver(), deps=deps)

    state = _initial_state(request_ctx=request_ctx, channel="web_form", channel_message="Quiero agendar una cita")
    config = {"configurable": {"thread_id": f"{seeded['tenant_id']}:{user_id}:thread-1"}}

    result = await graph.ainvoke(state, config)

    assert result["scope_ok"] is True
    assert result["consent_ok"] is True
    assert result["rbac_ok"] is True
    assert result["confirmation"] == "not_required"
    assert result["outcome"] is not None
    assert result["outcome"].success is True
    assert result["response_scope_ok"] is True
    assert result["response_text"]
    assert "Cita agendada" in result["response_text"]

    audit_count = (
        await rls_conn.execute(
            sa.text("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND action = 'appointment.create'"),
            {"t": seeded["tenant_id"]},
        )
    ).scalar_one()
    assert audit_count == 1


async def test_confirmation_round_trip_through_the_real_compiled_graph(rls_conn) -> None:
    seeded = await _seed_schedulable_tenant(rls_conn)
    user_id = "22222222-2222-2222-2222-222222222222"
    # `patient_id` is set directly here -- this test exercises the graph's
    # ROUTING/wiring, not `consent_gate`'s own already-flagged, unresolved
    # "staff_copilot on behalf of a different patient" positioning gap
    # (batch 1's docstring in `nodes/consent_gate.py`); a real turn resolving
    # WHICH patient a reception actor means is a separate, open question.
    request_ctx = RequestContext(
        tenant_id=seeded["tenant_id"],
        role="reception",
        site_id=seeded["site_id"],
        user_id=user_id,
        patient_id=seeded["patient_id"],
    )
    await set_app_context(rls_conn, tenant_id=seeded["tenant_id"], site_id=seeded["site_id"], role="reception", user_id=user_id)

    affirmation_classifier = _SequencedAffirmationClassifier()
    intent_classifier = _FakeIntentClassifier("schedule")
    deps = GraphDependencies(
        intent_classifier=intent_classifier,
        scope_policy=_FakeScopePolicy(),
        scheduling_planner=_FakeSchedulingPlanner(
            action="appointment:create",
            kwargs={
                "patient_id": seeded["patient_id"],
                "professional_id": seeded["professional_id"],
                "site_id": seeded["site_id"],
                "availability_id": seeded["availability_id"],
            },
            summary="Cita agendada con el profesional el 2026-09-01 09:00",
        ),
        affirmation_classifier=affirmation_classifier,
    )
    checkpointer = MemorySaver()
    graph = await build_graph(rls_conn, checkpointer=checkpointer, deps=deps)
    config = {"configurable": {"thread_id": f"{seeded['tenant_id']}:{user_id}:thread-2"}}

    # Turn N: staff_copilot channel, mutating action -> confirmation_gate
    # must ASK, never execute yet.
    turn_n_state = _initial_state(
        request_ctx=request_ctx, channel="staff_copilot", channel_message="Quiero agendar una cita para el paciente"
    )
    turn_n_result = await graph.ainvoke(turn_n_state, config)

    assert turn_n_result["confirmation"] == "needed"
    assert turn_n_result["proposed_action"] is not None
    assert turn_n_result["outcome"] is None
    assert "Confirmas" in turn_n_result["response_text"]

    # Turn N+1: same thread_id -- route_from_start must detect the pending
    # proposed_action and jump straight to confirmation_gate, which must
    # now treat "affirmed" as a reply to the already-asked prompt.
    turn_n_plus_1_input = {"request_ctx": request_ctx, "channel": "staff_copilot", "channel_message": "sí, confirmo"}
    turn_n_plus_1_result = await graph.ainvoke(turn_n_plus_1_input, config)

    assert turn_n_plus_1_result["confirmation"] == "affirmed"
    assert turn_n_plus_1_result["outcome"] is not None
    assert turn_n_plus_1_result["outcome"].success is True
    assert affirmation_classifier.calls == 2

    # Regression (CRITICAL finding, post-batch-3 verify pass): `respond`
    # MUST clear `proposed_action` once the turn concludes -- `KurehaState`
    # has no reducers, so LangGraph's default `LastValue` channel would
    # otherwise keep turn N+1's completed action in the checkpoint forever,
    # misrouting every subsequent turn straight back into `confirmation_gate`
    # via `route_from_start`. `confirmation` itself stays "affirmed" (this
    # turn's real outcome) -- only `proposed_action` is the routing signal.
    assert turn_n_plus_1_result["proposed_action"] is None
    assert turn_n_plus_1_result["confirmation"] == "affirmed"

    # Turn N+2: an entirely unrelated message on the SAME thread_id. With the
    # checkpoint correctly cleaned, `route_from_start` must send this to
    # `triage` (proven by `intent_classifier` being called again), NOT
    # shortcut straight to `confirmation_gate` with the already-executed
    # turn N+1 action -- which would otherwise re-run `persist_and_audit`
    # against an availability slot already reserved and fail.
    calls_before_turn_n_plus_2 = intent_classifier.calls
    turn_n_plus_2_input = {"request_ctx": request_ctx, "channel": "staff_copilot", "channel_message": "otra cosa"}
    turn_n_plus_2_result = await graph.ainvoke(turn_n_plus_2_input, config)

    assert intent_classifier.calls == calls_before_turn_n_plus_2 + 1
    assert turn_n_plus_2_result["confirmation"] == "needed"
