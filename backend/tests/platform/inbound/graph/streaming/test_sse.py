import json

from app.platform.inbound.graph.streaming.sse import format_sse_event


def test_format_sse_event_produces_the_exact_wire_shape() -> None:
    result = format_sse_event("status", {"phase": "checking_availability", "label": "Consultando disponibilidad"})

    assert result == (
        'event: status\ndata: {"phase": "checking_availability", '
        '"label": "Consultando disponibilidad"}\n\n'
    )


def test_format_sse_event_data_line_is_valid_json() -> None:
    result = format_sse_event("done", {"audit_ref": None, "calendar_sync_status": "ok", "finish_reason": "stop"})

    data_line = result.split("\n")[1]
    assert data_line.startswith("data: ")
    payload = json.loads(data_line[len("data: ") :])
    assert payload == {"audit_ref": None, "calendar_sync_status": "ok", "finish_reason": "stop"}


def test_format_sse_event_ends_with_a_blank_line_terminator() -> None:
    result = format_sse_event("token", {"delta": "hola"})

    assert result.endswith("\n\n")


def test_format_sse_event_serializes_non_json_native_values_via_str_fallback() -> None:

    class _Weird:
        def __str__(self) -> str:
            return "weird-value"

    result = format_sse_event("error", {"detail": _Weird()})

    assert '"detail": "weird-value"' in result
