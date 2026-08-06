import json
from typing import Any


def format_sse_event(event: str, data: dict[str, Any]) -> str:
    """`default=str` keeps a mid-stream serialize failure from crashing SSE."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
