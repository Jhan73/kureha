import { parseJsonOrThrow, type AuthorizedFetch } from "./client";
import type {
  AppointmentResponse,
  ReminderResponse,
  RescheduleAppointmentParams,
  ScheduleAppointmentParams,
} from "./types";

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
