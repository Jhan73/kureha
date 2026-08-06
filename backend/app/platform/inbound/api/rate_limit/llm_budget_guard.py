from datetime import datetime, timezone

from app.modules.governance.audit.application.ports.driven.audit_log import AuditLogPort
from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.platform.inbound.api.audit_safety import record_audit_best_effort
from app.platform.inbound.api.rate_limit.errors import LlmBudgetExceededError
from app.platform.inbound.api.rate_limit.rate_counter_store import RateCounterStorePort
from app.shared_kernel.clock import ClockPort

_DIMENSION = "llm_tokens"


class LlmBudgetGuard:
    def __init__(
        self,
        counter_store: RateCounterStorePort,
        *,
        clock: ClockPort,
        record_audit: AuditLogPort,
    ) -> None:
        self._counter_store = counter_store
        self._clock = clock
        self._record_audit = record_audit

    async def check(self, *, tenant_id: str, daily_budget_tokens: int) -> None:
        # Soft backstop: concurrent turns can pass before any records usage.
        window_start = self._today_window_start()
        consumed = await self._counter_store.peek(
            dimension=_DIMENSION, subject=tenant_id, window_start=window_start, tenant_id=tenant_id
        )
        if consumed >= daily_budget_tokens:
            # Best-effort audit must not mask LlmBudgetExceededError.
            await record_audit_best_effort(
                self._record_audit,
                AuditEntry(
                    tenant_id=tenant_id,
                    actor_type=AuditActorType.SYSTEM,
                    action=AuditAction.LLM_BUDGET_EXCEEDED,
                    object_type="tenant",
                    object_id=tenant_id,
                    payload={"consumed": consumed, "budget": daily_budget_tokens},
                ),
            )
            raise LlmBudgetExceededError(f"tenant {tenant_id} exceeded its daily LLM token budget")

    async def record_usage(self, *, tenant_id: str, tokens_used: int) -> int:
        window_start = self._today_window_start()
        return await self._counter_store.increment(
            dimension=_DIMENSION, subject=tenant_id, window_start=window_start, by=tokens_used, tenant_id=tenant_id
        )

    def _today_window_start(self) -> datetime:
        now = self._clock.now()
        return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
