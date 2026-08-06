class UnwiredAppointmentSnapshotAdapter:
    async def get_snapshot(self, tenant_id: str, appointment_id: str):
        raise NotImplementedError(
            "UnwiredAppointmentSnapshotAdapter is a placeholder -- "
            "wire a real AppointmentSnapshotPort before using."
        )
