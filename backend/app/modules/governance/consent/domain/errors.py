from app.shared_kernel.errors import DomainError


class ConsentNotCurrentError(DomainError):
    """No CURRENT accepted consent; patient_id for server logs only (never in user envelope)."""

    def __init__(self, patient_id: str) -> None:
        super().__init__(f"Patient {patient_id} does not have a current consent on file")
        self.patient_id = patient_id
