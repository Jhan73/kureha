"""`LlmBudgetGuard` (design.md §19, tasks.md task 5.3b): the LLM daily
budget cap backstop, implementing design.md's exact pseudocode --

```python
consumed = get_or_create_counter("llm_tokens", tenant_id, window_start=today)
budget   = tenants.llm_daily_budget_tokens
if consumed.count >= budget:
    raise LLMBudgetExceededError()
```

`check()` is a genuine READ of the current window's counter via
`RateCounterStorePort.peek` -- no side effect, unlike the earlier
`increment(..., by=0, ...)` fake-read (the UPSERT's `INSERT` branch still
created a `count=0` row even though `by=0` never mutated an existing one).
`record_usage()` is the separate UPSERT-by-tokens-used step design.md
describes running "al finalizar el turno". Both are scoped to TODAY's window
(`date_trunc('day', ...)` equivalent, computed in application code like
`FixedWindowRateLimiter`)."""

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
        # Soft/best-effort guarantee, not a hard atomic limit: there is a
        # window between this read and the later `record_usage()` call
        # (after the LLM call actually completes) during which concurrent
        # requests could each pass `check()` and collectively exceed
        # `daily_budget_tokens` before any of them records usage. Matches
        # design.md §19's own framing of the LLM daily budget as a
        # "backstop" ("un budget cap de LLM por tenant/dia como backstop"),
        # not a strict security boundary -- making this fully atomic would
        # require reserving an estimated token cost before the LLM call
        # runs, which is out of scope for this phase.
        window_start = self._today_window_start()
        consumed = await self._counter_store.peek(
            dimension=_DIMENSION, subject=tenant_id, window_start=window_start, tenant_id=tenant_id
        )
        if consumed >= daily_budget_tokens:
            # Fresh-review CRITICAL fix #3: `record_audit_best_effort`
            # swallows any failure from the write itself so it can never
            # mask the `LlmBudgetExceededError` below -- callers that
            # specifically catch it must always see it raised.
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
