from typing import Protocol


class PatientEmailLookupPort(Protocol):
    async def get_registered_email(self, tenant_id: str, patient_id: str) -> str | None:
        """Returns the patient's registered email, or `None` if the patient
        has no email on file (`patients.email` is nullable, migration
        8fc0dc6f958d) -- callers treat `None` as "nothing to compare against",
        never as a mismatch by itself."""
        ...
