"""SSE wire-format helper (design.md §8.5, tasks.md task 12.1): the exact
`event: {type}\\ndata: {json}\\n\\n` frame shape design.md's own example
shows. The single place `/chat/stream` (`platform/inbound/api/routers/
chat.py`) formats every `status`/`token`/`done`/`error` event -- no other
module builds an SSE frame string by hand."""

import json
from typing import Any


def format_sse_event(event: str, data: dict[str, Any]) -> str:
    """`default=str` is a defensive fallback -- every real payload this
    codebase emits (`{"phase", "label"}`/`{"delta"}`/`{"audit_ref",
    "calendar_sync_status", "finish_reason"}`/the §21 error envelope) is
    already JSON-native, but a genuinely non-serializable value reaching
    here should degrade to its `str()` rather than crash an in-progress
    stream."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
