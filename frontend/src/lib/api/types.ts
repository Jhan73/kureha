// Shape of the backend's `TokenResponse` (see
// backend/app/platform/inbound/api/routers/auth.py). Field names stay in
// snake_case to mirror the wire format exactly -- no client-side renaming.
export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  user_id: string;
  role: string;
}

export interface LoginParams {
  tenantId: string;
  email: string;
  password: string;
}

// Shape of the backend's `AppointmentResponse` / `ReminderResponse` (see
// backend/app/platform/inbound/api/routers/scheduling.py). Field names stay
// in snake_case to mirror the wire format exactly -- no client-side renaming.
export interface AppointmentResponse {
  id: string;
  tenant_id: string;
  site_id: string;
  patient_id: string;
  professional_id: string;
  starts_at: string;
  ends_at: string;
  status: string;
}

export interface ReminderResponse {
  delivered: boolean;
}

export interface ScheduleAppointmentParams {
  patientId: string;
  professionalId: string;
  siteId: string;
  availabilityId: string;
}

export interface RescheduleAppointmentParams {
  appointmentId: string;
  newAvailabilityId: string;
}
