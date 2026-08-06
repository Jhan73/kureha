import base64
import uuid


def derive_idempotency_key(appointment_id: str) -> str:
    raw = uuid.UUID(appointment_id).bytes
    encoded = base64.b32hexencode(raw).decode("ascii").rstrip("=").lower()
    return f"kureha{encoded}"
