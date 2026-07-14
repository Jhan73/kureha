"""Task 3.4: `ClinicalScopePolicy` inbound+outbound classifier interface
(design.md §8.7). Only the interface/value objects are in scope for this
task -- the LLM-backed classifier adapter lands in tasks.md Phase 12."""

import inspect

from app.modules.governance.scope.domain.scope_policy import (
    ClinicalScopePolicy,
    InboundScopeCategory,
    InboundScopeResult,
    OutboundScopeCategory,
    OutboundScopeResult,
)


def test_inbound_scope_category_covers_the_three_refusal_triggers() -> None:
    """design.md §8.7: intent clinico/diagnostico, prompt injection/jailbreak,
    y framing de fuga tenant/scope -- las tres se rehusan igual."""
    assert {c.value for c in InboundScopeCategory} == {
        "in_scope",
        "clinical_diagnosis",
        "prompt_injection",
        "tenant_scope_leakage",
    }


def test_outbound_scope_category_covers_leakage_and_clinical_content() -> None:
    assert {c.value for c in OutboundScopeCategory} == {
        "safe",
        "clinical_content",
        "tenant_scope_leakage",
    }


def test_inbound_scope_result_flags_escalation_for_non_in_scope_categories() -> None:
    result = InboundScopeResult(category=InboundScopeCategory.PROMPT_INJECTION, should_escalate=True)

    assert result.category == InboundScopeCategory.PROMPT_INJECTION
    assert result.should_escalate is True


def test_outbound_scope_result_flags_blocking_for_unsafe_categories() -> None:
    result = OutboundScopeResult(category=OutboundScopeCategory.CLINICAL_CONTENT, should_block=True)

    assert result.category == OutboundScopeCategory.CLINICAL_CONTENT
    assert result.should_block is True


def test_clinical_scope_policy_is_an_async_protocol_with_inbound_and_outbound_methods() -> None:
    assert hasattr(ClinicalScopePolicy, "classify_inbound")
    assert hasattr(ClinicalScopePolicy, "classify_outbound")
    assert inspect.iscoroutinefunction(ClinicalScopePolicy.classify_inbound)
    assert inspect.iscoroutinefunction(ClinicalScopePolicy.classify_outbound)


def test_classify_methods_take_a_tenant_context() -> None:
    """`TENANT_SCOPE_LEAKAGE` (both categories) is meaningless without
    knowing which tenant "leakage" is relative to -- both methods must
    accept `ctx` so the Phase 12 adapter isn't forced into a breaking
    signature change later. Matches the pattern `AuthorizationPort.is_allowed`
    and `CheckConsent.execute` already use (design.md §5/§11)."""
    inbound_params = list(inspect.signature(ClinicalScopePolicy.classify_inbound).parameters)
    outbound_params = list(inspect.signature(ClinicalScopePolicy.classify_outbound).parameters)

    assert "ctx" in inbound_params
    assert "ctx" in outbound_params
