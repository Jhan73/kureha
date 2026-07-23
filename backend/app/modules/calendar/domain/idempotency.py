"""`derive_idempotency_key` (ADR-18, design.md §7.6, tasks.md task 9.3):
deterministic Google Calendar event id derived purely from `appointment_id`
-- two independent attempts (e.g. an original request and a later retry job
run) compute the exact SAME key without reading any prior state, which is
what makes `GoogleCalendarAdapter.upsert_event`'s retry-safety possible (a
`409` on `events.insert` means "this exact id already exists", not "id
collision with something else").

Google requires event ids to match `^[a-v0-9]{5,1024}$` -- **base32hex**
(RFC 4648 §7, alphabet `0-9a-v`), NOT standard base32 (RFC 4648 §6, alphabet
`A-Z2-7`), is what keeps the lowercased encoding inside that charset; using
the wrong alphabet would silently produce invalid ids for most inputs
(flagged here since this exact mistake is easy to make -- `base64.b32encode`
and `base64.b32hexencode` look interchangeable but are not). A UUID's 128
bits encode to 26 base32hex characters once the `=` padding (needed only to
pad the encoded LENGTH to a multiple of 8, not required by Google's charset)
is stripped. The `kureha` prefix namespaces Kureha's own ids in a shared
Google Calendar (least ambiguity if ever inspected manually) and both
satisfies and comfortably clears Google's 5-character minimum."""

import base64
import uuid


def derive_idempotency_key(appointment_id: str) -> str:
    raw = uuid.UUID(appointment_id).bytes
    encoded = base64.b32hexencode(raw).decode("ascii").rstrip("=").lower()
    return f"kureha{encoded}"
