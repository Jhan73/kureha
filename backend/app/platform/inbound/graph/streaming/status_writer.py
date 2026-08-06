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
