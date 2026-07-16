"""CRITICAL fixes #1/#3 (fresh-review pass, kureha-mvp PR 6):
`record_audit_best_effort` -- the shared helper `AccessControlMiddleware`,
`AuthRateLimitMiddleware`, and `LlmBudgetGuard` all use to write an audit
entry without letting a failure in `AuditLogPort.record()` propagate and
override the security/rate-limit/budget decision already made."""

import logging

from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.platform.inbound.api.audit_safety import record_audit_best_effort


class _FakeAuditLog:
    def __init__(self) -> None:
        self.recorded: list[AuditEntry] = []

    async def record(self, entry: AuditEntry) -> str:
        self.recorded.append(entry)
        return "audit-1"


class _FailingAuditLog:
    async def record(self, entry: AuditEntry) -> str:
        raise RuntimeError("audit backend unavailable")


def _entry() -> AuditEntry:
    return AuditEntry(
        tenant_id="t1",
        actor_type=AuditActorType.SYSTEM,
        action=AuditAction.AUTH_RATE_LIMITED,
        object_type="auth_rate_limit",
    )


async def test_writes_the_entry_when_the_port_succeeds() -> None:
    audit_log = _FakeAuditLog()

    await record_audit_best_effort(audit_log, _entry())

    assert len(audit_log.recorded) == 1
    assert audit_log.recorded[0].action == AuditAction.AUTH_RATE_LIMITED


async def test_swallows_the_exception_when_the_port_raises() -> None:
    # Must not raise -- callers rely on this being a fire-and-forget
    # best-effort write that never overrides the caller's own decision.
    await record_audit_best_effort(_FailingAuditLog(), _entry())


async def test_logs_a_warning_when_the_port_raises(caplog) -> None:
    # The `_migrated_schema` session fixture (conftest.py) runs Alembic's
    # `command.upgrade`, which calls `logging.config.fileConfig(alembic.ini)`
    # -- by default this DISABLES every logger that already existed at that
    # point (this module's logger, created at import time, included). Not a
    # production concern (Alembic runs as a separate CLI process before the
    # app starts there), but this test-only harness quirk means the logger
    # must be explicitly re-enabled here.
    logging.getLogger("app.platform.inbound.api.audit_safety").disabled = False

    with caplog.at_level(logging.WARNING, logger="app.platform.inbound.api.audit_safety"):
        await record_audit_best_effort(_FailingAuditLog(), _entry())

    assert any(record.levelno == logging.WARNING for record in caplog.records)
