from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

from app.modules.governance.rbac.domain.permission import ActionKey
from app.shared_kernel.tenant_context import TenantContext


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Graph-local identity; maps to TenantContext via to_tenant_context()."""

    tenant_id: str
    role: str
    site_id: str | None = None
    user_id: str | None = None
    patient_id: str | None = None
    professional_id: str | None = None

    def to_tenant_context(self) -> TenantContext:
        """Maps user_id → actor_id; patient_id/professional_id stay graph-local."""
        return TenantContext(tenant_id=self.tenant_id, role=self.role, site_id=self.site_id, actor_id=self.user_id)


@dataclass(frozen=True, slots=True)
class ProposedAction:
    """Specialist plan not yet executed; payload shape is action-specific."""

    action: ActionKey
    is_mutating: bool
    payload: dict[str, Any] = field(default_factory=dict)
    summary: str = ""


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    """HITL interrupt/resume payload."""

    approved: bool
    approved_by: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ActionOutcome:
    """Result of persist_and_audit."""

    success: bool
    result_id: str | None = None
    error: str | None = None


class KurehaState(TypedDict):
    """LangGraph turn state."""

    request_ctx: RequestContext
    channel: Literal["web_form", "patient_chat", "staff_copilot"]
    channel_message: str
    intent: (
        Literal[
            "schedule",
            "reschedule",
            "cancel",
            "reminder",
            "staff",
            "shift",
            "greeting",
            "capability_query",
            "small_talk",
            "unknown",
        ]
        | None
    )
    scope_ok: bool | None
    consent_ok: bool | None
    allowed_actions: list[str] | None
    proposed_action: ProposedAction | None
    rbac_ok: bool | None
    risk_level: Literal["low", "high"] | None
    confirmation: Literal["not_required", "needed", "affirmed"] | None
    approval: ApprovalDecision | None
    outcome: ActionOutcome | None
    audit_ref: str | None
    response_text: str | None
    response_scope_ok: bool | None
    calendar_sync_status: Literal["pending", "ok", "failed", "n/a"] | None
    suggestions: list[str] | None
