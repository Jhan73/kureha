"""`response_guard` node, OUTBOUND mode (design.md §8.2/§8.7, tasks.md task
11.5): delegates to `ClinicalScopePolicy.classify_outbound` (the SAME
Protocol `clinical_scope_validator`'s inbound mode already consumes,
`governance/scope/domain/scope_policy.py` -- that Protocol has had this
method since task 3.4, not redefined here) and sets
`state.response_scope_ok`.

**Non-streaming, single-shot for THIS batch -- deliberately.** design.md
§8.7's sentence-boundary chunk-buffering (`\\n`/`.`/`?`/`!` boundaries or
~80-token fallback, classified concurrently with generation) is tasks.md
task 12.4, explicitly a LATER phase (SSE streaming itself is task 12.1,
not built here). This node classifies `state.response_text` AS A WHOLE, in
one call -- correct for task 11.7's plain non-streaming `graph.ainvoke()`
chat endpoint, which has no per-chunk concept to buffer at all.

**Runs on `state.get("response_text") or ""` -- a deliberate, flagged
interpretation of design.md §8.3's edge diagram, not an oversight.** On the
conversational-shortcut paths (`direct_respond`, `confirmation_gate`'s
`needed`/decline branches), `response_text` is already real LLM/template
content by the time this node runs -- classified for real. On the
OPERATIONAL path (`persist_and_audit`/`calendar_sync` -> `response_guard`),
NO upstream node in that path sets `response_text` before this one runs
(`respond`, the node that composes it, runs AFTER `response_guard` per
design.md's own edge diagram) -- so this node necessarily classifies an
EMPTY string here, which resolves vacuously "safe"
(`response_scope_ok=True`) unless the classifier itself treats "" specially.
This is intentional, not a gap: `respond`'s own composition on that path is
template-based from structured fields (`outcome`/`audit_ref`/
`calendar_sync_status`), never free LLM generation, so it carries none of
the clinical-content-leak risk this guardrail exists to catch -- see
`respond.py`'s own module docstring for the same judgment call from the
other side. Flagged here explicitly in case a future revision wants
LLM-generated flourish text in `respond`'s composition, which WOULD need a
second guard pass this graph's current edges do not provide."""

from app.modules.governance.scope.domain.scope_policy import ClinicalScopePolicy, OutboundScopeCategory
from app.platform.inbound.graph.state import KurehaState


def make_response_guard_node(scope_policy: ClinicalScopePolicy):
    async def response_guard(state: KurehaState) -> dict:
        ctx = state["request_ctx"].to_tenant_context()
        result = await scope_policy.classify_outbound(ctx, state.get("response_text") or "")
        return {"response_scope_ok": result.category is OutboundScopeCategory.SAFE}

    return response_guard
