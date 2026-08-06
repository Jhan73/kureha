import type { AppointmentResponse } from "@/lib/api/types";

export function AppointmentSummary({ appointment }: { appointment: AppointmentResponse }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
      <dt className="text-muted-foreground">Appointment ID</dt>
      <dd>{appointment.id}</dd>
      <dt className="text-muted-foreground">Status</dt>
      <dd>{appointment.status}</dd>
      <dt className="text-muted-foreground">Starts</dt>
      <dd>{new Date(appointment.starts_at).toLocaleString()}</dd>
      <dt className="text-muted-foreground">Ends</dt>
      <dd>{new Date(appointment.ends_at).toLocaleString()}</dd>
      <dt className="text-muted-foreground">Professional</dt>
      <dd>{appointment.professional_id}</dd>
      <dt className="text-muted-foreground">Site</dt>
      <dd>{appointment.site_id}</dd>
    </dl>
  );
}
