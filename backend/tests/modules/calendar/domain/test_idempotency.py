"""Task 9.3/ADR-18 (design.md §7.6): `derive_idempotency_key` -- a deterministic
Google Calendar event id derived purely from `appointment_id`, so retries
compute the exact same key without reading prior state. Must satisfy
Google's event-id charset (`^[a-v0-9]{5,1024}$`)."""

import base64
import re
import uuid

from app.modules.calendar.domain.idempotency import derive_idempotency_key

_CHARSET = re.compile(r"^[a-v0-9]{5,1024}$")


def test_key_is_deterministic_for_the_same_appointment_id() -> None:
    appointment_id = str(uuid.uuid4())

    first = derive_idempotency_key(appointment_id)
    second = derive_idempotency_key(appointment_id)

    assert first == second


def test_key_differs_across_appointment_ids() -> None:
    assert derive_idempotency_key(str(uuid.uuid4())) != derive_idempotency_key(str(uuid.uuid4()))


def test_key_starts_with_kureha_prefix() -> None:
    key = derive_idempotency_key(str(uuid.uuid4()))

    assert key.startswith("kureha")


def test_key_matches_google_calendar_event_id_charset() -> None:
    key = derive_idempotency_key(str(uuid.uuid4()))

    assert _CHARSET.match(key), f"{key!r} does not match Google's event id charset"


def test_key_matches_base32hex_lower_encoding_of_the_uuid_bytes() -> None:
    appointment_id = str(uuid.uuid4())
    raw = uuid.UUID(appointment_id).bytes
    expected = "kureha" + base64.b32hexencode(raw).decode("ascii").rstrip("=").lower()

    assert derive_idempotency_key(appointment_id) == expected


def test_key_differs_from_standard_base32_encoding() -> None:
    # Base32hex (RFC 4648 §7, alphabet 0-9a-v) is NOT standard base32
    # (RFC 4648 §6, alphabet A-Z2-7) -- using the wrong one would produce
    # chars outside Google's required a-v0-9 charset for most inputs.
    appointment_id = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    raw = uuid.UUID(appointment_id).bytes
    std_b32 = base64.b32encode(raw).decode("ascii").rstrip("=").lower()

    assert derive_idempotency_key(appointment_id) != "kureha" + std_b32
