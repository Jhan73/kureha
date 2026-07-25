"""`emit_status` (design.md §8.5/§8.7, tasks.md task 12.2): the ONLY place a
graph node calls `get_stream_writer()` -- every node wanting to surface an
intermediate `custom`-stream_mode status event goes through this helper, not
`get_stream_writer()` directly, for two reasons both proven by this module's
own tests:

1. **RBAC-scoping (spec `internal-staff-copilot`, "Streaming status shows
   only permitted tool activity"):** a status event tied to a specific
   `action` MUST NOT be emitted unless that action is in the caller's own
   `allowed_actions` -- centralizing this check here means no node can
   accidentally leak a disallowed tool name by forgetting the check inline.
   `action=None` means the phase is administrative/generic (not tied to any
   one RBAC-gated action, e.g. "resolving the toolset" itself) -- always
   emitted.
2. **Safe outside a running graph.** `get_stream_writer()` (confirmed
   empirically, `langgraph.config`) raises `RuntimeError` when called
   outside an active LangGraph runnable context -- which is exactly how
   EVERY existing node in this package is unit-tested (the bare node
   function called directly, never through a compiled graph, e.g.
   `test_scheduling_agent.py`). Without this guard, adding a single
   `get_stream_writer()` call to any node would break every one of that
   node's own existing tests. `get_stream_writer` is imported at MODULE
   level (not inside the function) specifically so tests can monkeypatch
   `status_writer.get_stream_writer` without needing to patch
   `langgraph.config` globally."""

from langgraph.config import get_stream_writer


def emit_status(*, phase: str, label: str, action: str | None = None, allowed_actions: list[str] | None = None) -> None:
    if action is not None and (not allowed_actions or action not in allowed_actions):
        return
    try:
        writer = get_stream_writer()
    except RuntimeError:
        # Outside a running graph (e.g. a node under direct unit test, or a
        # plain `graph.ainvoke()` call with no active `custom` stream
        # subscriber) -- status-event emission is best-effort telemetry,
        # never a functional part of a node's own return contract.
        return
    writer({"phase": phase, "label": label})
