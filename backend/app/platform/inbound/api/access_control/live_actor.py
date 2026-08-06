from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LiveActor:
    user_id: str
    tenant_id: str
    site_id: str
    role: str
    status: str
    patient_id: str | None
    professional_id: str | None
    staff_status: str | None  # staff_members.status, or None if no staff row

    @property
    def is_active(self) -> bool:
        """Active iff users.status is active and staff_status is None or active."""
        if self.status != "active":
            return False
        return self.staff_status is None or self.staff_status == "active"
