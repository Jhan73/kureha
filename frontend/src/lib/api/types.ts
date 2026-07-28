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

// Shape of the backend's §21 error envelope (see
// backend/app/platform/inbound/api/errors.py / design.md §21), reused
// verbatim for the `/chat/stream` SSE `error` event payload.
export interface ErrorEnvelope {
  error_code: string;
  category: string;
  user_message: string;
  retryable: boolean;
  correlation_id: string;
}

// The four SSE event shapes `POST /chat/stream` emits (design.md §8.5,
// backend/app/platform/inbound/api/routers/chat.py's `_stream_turn`).
// `type` here is a client-side discriminant added while parsing the wire
// `event: {type}` line -- it does not appear in the JSON `data:` payload
// itself.
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
