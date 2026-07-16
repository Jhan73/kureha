"""Task 5.3b: `LlmBudgetGuard` -- design.md §19's LLM daily budget cap
backstop. `check()` reads (without mutating) the tenant's `llm_tokens`
counter for TODAY's window and raises+audits once `consumed >= budget`
(`llm.budget_exceeded`, per design.md's exact pseudocode). `record_usage()`
is the separate UPSERT-by-tokens-used step run at the end of a turn. Fake
counter store + fake audit sink only -- the real UPSERT is proven by
`test_postgres_rate_counter_store.py`."""

from datetime import datetime, timezone

import pytest

from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditEntry
from app.platform.inbound.api.rate_limit.errors import LlmBudgetExceededError
from app.platform.inbound.api.rate_limit.llm_budget_guard import LlmBudgetGuard


class _FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class _FakeCounterStore:
    def __init__(self, *, initial: dict[tuple, int] | None = None) -> None:
        self._counts: dict[tuple, int] = dict(initial or {})
        self.calls: list[dict] = []
        self.peek_calls: list[dict] = []

    async def increment(self, *, dimension, subject, window_start, by=1, tenant_id=None) -> int:
        self.calls.append(
            {"dimension": dimension, "subject": subject, "window_start": window_start, "by": by}
        )
        key = (dimension, subject, window_start)
        self._counts[key] = self._counts.get(key, 0) + by
        return self._counts[key]

    async def peek(self, *, dimension, subject, window_start, tenant_id=None) -> int:
        self.peek_calls.append({"dimension": dimension, "subject": subject, "window_start": window_start})
        return self._counts.get((dimension, subject, window_start), 0)


class _FakeAuditLog:
    """Mirrors `tests/modules/identity/application/test_login.py::_FakeAuditLog`
    / `test_middleware.py::_FakeAuditLog` -- the `AuditLogPort` fake pattern
    already established elsewhere in the test suite."""

    def __init__(self, sink: list[AuditEntry]) -> None:
        self._sink = sink

    async def record(self, entry: AuditEntry) -> str:
        self._sink.append(entry)
        return "audit-1"


class _FailingAuditLog:
    """CRITICAL fix #3 (fresh-review pass, kureha-mvp PR 6): an
    `AuditLogPort` fake whose `record()` always raises, used to prove a
    failed audit write can never mask `LlmBudgetExceededError` -- callers
    that specifically catch it must still see it raised."""

    async def record(self, entry: AuditEntry) -> str:
        raise RuntimeError("audit backend unavailable")


def _guard(store: _FakeCounterStore, *, now: datetime, audit_sink: list[AuditEntry]) -> LlmBudgetGuard:
    return LlmBudgetGuard(store, clock=_FixedClock(now), record_audit=_FakeAuditLog(audit_sink))


_NOW = datetime(2026, 3, 15, 10, 30, 0, tzinfo=timezone.utc)
_TODAY_WINDOW = datetime(2026, 3, 15, tzinfo=timezone.utc)


async def test_check_passes_when_under_budget() -> None:
    store = _FakeCounterStore(initial={("llm_tokens", "t1", _TODAY_WINDOW): 500})
    audit_sink: list[AuditEntry] = []
    guard = _guard(store, now=_NOW, audit_sink=audit_sink)

    await guard.check(tenant_id="t1", daily_budget_tokens=1000)

    assert audit_sink == []
    # `check` must not mutate the counter -- it's a genuine read (`peek`),
    # not the old `increment(..., by=0, ...)` fake-read.
    assert store._counts[("llm_tokens", "t1", _TODAY_WINDOW)] == 500


async def test_check_uses_peek_and_never_calls_increment() -> None:
    """The old implementation called `increment(..., by=0, ...)` as a
    fake-read, which the atomic UPSERT still creates a row for even though
    `by=0` never mutates an existing one -- a genuine side effect on a
    "read" path. `check()` must now call `peek()` exclusively."""
    store = _FakeCounterStore()
    audit_sink: list[AuditEntry] = []
    guard = _guard(store, now=_NOW, audit_sink=audit_sink)

    await guard.check(tenant_id="new-tenant", daily_budget_tokens=1000)

    assert store.calls == []
    assert len(store.peek_calls) == 1
    assert store.peek_calls[0]["dimension"] == "llm_tokens"
    assert store.peek_calls[0]["subject"] == "new-tenant"
    assert store.peek_calls[0]["window_start"] == _TODAY_WINDOW


async def test_check_raises_and_audits_once_budget_is_reached() -> None:
    store = _FakeCounterStore(initial={("llm_tokens", "t1", _TODAY_WINDOW): 1000})
    audit_sink: list[AuditEntry] = []
    guard = _guard(store, now=_NOW, audit_sink=audit_sink)

    with pytest.raises(LlmBudgetExceededError):
        await guard.check(tenant_id="t1", daily_budget_tokens=1000)

    assert len(audit_sink) == 1
    assert audit_sink[0].action == AuditAction.LLM_BUDGET_EXCEEDED
    assert audit_sink[0].tenant_id == "t1"


async def test_check_raises_when_over_budget() -> None:
    store = _FakeCounterStore(initial={("llm_tokens", "t1", _TODAY_WINDOW): 1500})
    audit_sink: list[AuditEntry] = []
    guard = _guard(store, now=_NOW, audit_sink=audit_sink)

    with pytest.raises(LlmBudgetExceededError):
        await guard.check(tenant_id="t1", daily_budget_tokens=1000)


async def test_check_treats_a_tenant_with_no_counter_row_yet_as_zero_consumed() -> None:
    store = _FakeCounterStore()
    audit_sink: list[AuditEntry] = []
    guard = _guard(store, now=_NOW, audit_sink=audit_sink)

    await guard.check(tenant_id="new-tenant", daily_budget_tokens=1000)
    assert audit_sink == []


async def test_check_raises_budget_exceeded_even_when_the_audit_write_fails() -> None:
    """CRITICAL fix #3 (fresh-review pass): `record_audit.record()` raising
    must never prevent `LlmBudgetExceededError` from being raised -- the
    budget-exceeded decision always wins over a failed audit write."""
    store = _FakeCounterStore(initial={("llm_tokens", "t1", _TODAY_WINDOW): 1000})
    guard = LlmBudgetGuard(store, clock=_FixedClock(_NOW), record_audit=_FailingAuditLog())

    with pytest.raises(LlmBudgetExceededError):
        await guard.check(tenant_id="t1", daily_budget_tokens=1000)


async def test_record_usage_upserts_the_tokens_used_for_todays_window() -> None:
    store = _FakeCounterStore()
    audit_sink: list[AuditEntry] = []
    guard = _guard(store, now=_NOW, audit_sink=audit_sink)

    new_total = await guard.record_usage(tenant_id="t1", tokens_used=250)

    assert new_total == 250
    assert store.calls[-1]["by"] == 250
    assert store.calls[-1]["window_start"] == _TODAY_WINDOW
