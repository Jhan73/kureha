// Wire format is snake_case; do not rename client-side.
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

export interface BootstrapTenantParams {
  name: string;
  adminEmail: string;
  siteName?: string;
}

export type CredentialStatus = "invited" | "invite_failed";

export interface TenantBootstrapResponse {
  tenant_id: string;
  site_id: string;
  admin_user_id: string;
  admin_email: string;
  credential_status: CredentialStatus;
}

export interface RetryAdminInviteParams {
  siteId: string;
  adminUserId: string;
  adminEmail: string;
}

export interface AdminInviteResponse {
  tenant_id: string;
  admin_user_id: string;
  admin_email: string;
  credential_status: CredentialStatus;
}

export interface ErrorEnvelope {
  error_code: string;
  category: string;
  user_message: string;
  retryable: boolean;
  correlation_id: string;
}

// Discriminant from SSE `event:` line, not the JSON `data:` payload.
export interface ChatStatusEvent {
  type: "status";
  phase: string;
  label: string;
}

export interface ChatTokenEvent {
  type: "token";
  delta: string;
}

export interface ChatDoneEvent {
  type: "done";
  audit_ref: string | null;
  calendar_sync_status: string | null;
  finish_reason: string | null;
}

export interface ChatErrorEvent {
  type: "error";
  error: ErrorEnvelope;
}

export type ChatStreamEvent = ChatStatusEvent | ChatTokenEvent | ChatDoneEvent | ChatErrorEvent;
