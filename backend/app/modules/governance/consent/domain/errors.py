"""Consent-module error hierarchy (design.md §11), closing sdd-verify
`verify-report` #414's CRITICAL finding: spec `patient-self-service-portal`
-> "Consent Gate Enforced in Portal" was unimplemented full-stack for the
web-form channel (the backend caller was missing entirely -- a PR10-era gap
in `scheduling.py`, task 10.1's own scope, never wired -- see
`platform/inbound/api/routers/scheduling.py`'s module docstring for the
closure note).

`ConsentNotCurrentError` does not fit any of `shared_kernel.errors`'s four
subtypes (`NotFoundError`/`NotAuthorizedError`/`ValidationError`/
`ConflictError`) any more cleanly than `RateLimitExceededError` does (see
`platform/inbound/api/rate_limit/errors.py`'s own docstring for the same
reasoning) -- consent is its own governance plane, independent of RBAC
(`NotAuthorizedError`'s territory; design.md's RLS/RBAC/consent "neither
substitutes the other" framing applies here too, one plane deeper).
Subclassing `DomainError` directly keeps this catchable alongside every
other domain error without mischaracterizing the cause as an RBAC denial."""

from app.shared_kernel.errors import DomainError


class ConsentNotCurrentError(DomainError):
    """The patient has no CURRENT accepted consent on file. `ConsentPolicy
    .evaluate`'s three non-CURRENT outcomes (missing/outdated/revoked) are
    all treated identically here -- same collapsing `consent_gate` (the
    chat-channel equivalent, `platform/inbound/graph/nodes/consent_gate.py`)
    already does via its own `consent_ok: bool`. Carries `patient_id` for
    server-side logging only -- never included in the user-facing envelope
    (`platform/inbound/api/errors.py`'s `user_message` is always curated,
    never derived from the exception, per design.md §21.2)."""

    def __init__(self, patient_id: str) -> None:
        super().__init__(f"Patient {patient_id} does not have a current consent on file")
        self.patient_id = patient_id
