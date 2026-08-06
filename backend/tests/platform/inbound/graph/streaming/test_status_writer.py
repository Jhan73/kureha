import pytest

from app.platform.inbound.graph.streaming import status_writer


class _RecordingWriter:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def __call__(self, payload: dict) -> None:
        self.events.append(payload)


def _patch_writer(monkeypatch, writer) -> None:
    monkeypatch.setattr(status_writer, "get_stream_writer", lambda: writer)


def _raise_not_in_context():
    raise RuntimeError("Called get_config outside of a runnable context")


def test_emit_status_writes_the_event_when_action_is_none(monkeypatch) -> None:
    writer = _RecordingWriter()
    _patch_writer(monkeypatch, writer)

    status_writer.emit_status(phase="resolving_toolset", label="Resolviendo permisos")

    assert writer.events == [{"phase": "resolving_toolset", "label": "Resolviendo permisos"}]


def test_emit_status_writes_the_event_when_action_is_in_allowed_actions(monkeypatch) -> None:
    writer = _RecordingWriter()
    _patch_writer(monkeypatch, writer)

    status_writer.emit_status(
        phase="checking_availability",
        label="Consultando disponibilidad",
        action="appointment:create",
        allowed_actions=["appointment:create", "appointment:cancel"],
    )

    assert writer.events == [{"phase": "checking_availability", "label": "Consultando disponibilidad"}]


def test_emit_status_suppresses_the_event_when_action_is_not_allowed(monkeypatch) -> None:
    def _fail_if_called():
        raise AssertionError("get_stream_writer must not be reached for a disallowed action")

    monkeypatch.setattr(status_writer, "get_stream_writer", _fail_if_called)

    status_writer.emit_status(
        phase="cancelling_appointment",
        label="Cancelando cita",
        action="appointment:cancel",
        allowed_actions=["appointment:create"],
    )
    # no assertion needed beyond "did not raise" -- `_fail_if_called` above
    # proves the writer was never even constructed.


def test_emit_status_suppresses_the_event_when_allowed_actions_is_none() -> None:
    def _fail_if_called():
        raise AssertionError("get_stream_writer must not be reached with no allowed_actions at all")

    import app.platform.inbound.graph.streaming.status_writer as module

    original = module.get_stream_writer
    module.get_stream_writer = _fail_if_called
    try:
        status_writer.emit_status(
            phase="cancelling_appointment", label="Cancelando cita", action="appointment:cancel", allowed_actions=None
        )
    finally:
        module.get_stream_writer = original


def test_emit_status_is_a_no_op_outside_a_running_graph(monkeypatch) -> None:
    monkeypatch.setattr(status_writer, "get_stream_writer", _raise_not_in_context)

    status_writer.emit_status(phase="resolving_toolset", label="Resolviendo permisos")
    # did not raise -- that is the entire assertion.


async def test_emit_status_matches_the_real_get_stream_writer_contract() -> None:
    with pytest.raises(RuntimeError):
        status_writer.get_stream_writer()
