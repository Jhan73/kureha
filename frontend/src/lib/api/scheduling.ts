import { parseJsonOrThrow, type AuthorizedFetch } from "./client";
import type {
  AppointmentResponse,
  ReminderResponse,
  RescheduleAppointmentParams,
  ScheduleAppointmentParams,
} from "./types";

/**
 * Thin wrappers over the backend's deterministic web-form routes (tasks.md
 * 14.2, mirrors `backend/app/platform/inbound/api/routers/scheduling.py`'s
 * `POST /appointments/schedule|{id}/reschedule|{id}/cancel|{id}/reminder`).
 * Every call goes through the caller-supplied `authorizedFetch` (see
 * `lib/auth/auth-context.tsx`) so the bearer token and 401 refresh-retry are
 * handled the same way as every other authenticated request -- there is no
 * separate auth handling here.
 */

function jsonHeaders(): Record<string, string> {
  return { "Content-Type": "application/json" };
}

export async function scheduleAppointment(
  authorizedFetch: AuthorizedFetch,
  params: ScheduleAppointmentParams,
): Promise<AppointmentResponse> {
  const response = await authorizedFetch("/appointments/schedule", {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({
      patient_id: params.patientId,
      professional_id: params.professionalId,
      site_id: params.siteId,
      availability_id: params.availabilityId,
    }),
  });
  return parseJsonOrThrow<AppointmentResponse>(response);
}

export async function rescheduleAppointment(
  authorizedFetch: AuthorizedFetch,
  params: RescheduleAppointmentParams,
): Promise<AppointmentResponse> {
  const response = await authorizedFetch(`/appointments/${params.appointmentId}/reschedule`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ new_availability_id: params.newAvailabilityId }),
  });
  return parseJsonOrThrow<AppointmentResponse>(response);
}

export async function cancelAppointment(
  authorizedFetch: AuthorizedFetch,
  appointmentId: string,
): Promise<AppointmentResponse> {
  const response = await authorizedFetch(`/appointments/${appointmentId}/cancel`, {
    method: "POST",
  });
  return parseJsonOrThrow<AppointmentResponse>(response);
}

export async function sendReminder(
  authorizedFetch: AuthorizedFetch,
  appointmentId: string,
): Promise<ReminderResponse> {
  const response = await authorizedFetch(`/appointments/${appointmentId}/reminder`, {
    method: "POST",
  });
  return parseJsonOrThrow<ReminderResponse>(response);
}
