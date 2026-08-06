from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CalendarConnected:
    credential_id: str


@dataclass(frozen=True, slots=True)
class CalendarEmailMismatch:
    registered_email: str
    google_email: str
