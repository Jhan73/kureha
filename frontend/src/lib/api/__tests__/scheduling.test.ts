import { describe, expect, it, vi } from "vitest";
import {
  cancelAppointment,
  rescheduleAppointment,
  scheduleAppointment,
  sendReminder,
} from "../scheduling";
import { ApiError } from "../client";
import type { AppointmentResponse, ReminderResponse } from "../types";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const appointment: AppointmentResponse = {
  id: "appt-1",
  tenant_id: "tenant-1",
  site_id: "site-1",
  patient_id: "patient-1",
  professional_id: "prof-1",
  starts_at: "2026-08-01T10:00:00Z",
  ends_at: "2026-08-01T10:30:00Z",
  status: "scheduled",
};

describe("scheduleAppointment", () => {
  it("posts the new-appointment payload and returns the created appointment", async () => {
    const authorizedFetch = vi.fn().mockResolvedValueOnce(jsonResponse(201, appointment));

    const result = await scheduleAppointment(authorizedFetch, {
      patientId: "patient-1",
      professionalId: "prof-1",
      siteId: "site-1",
      availabilityId: "slot-1",
    });

    expect(authorizedFetch).toHaveBeenCalledWith(
      "/appointments/schedule",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          patient_id: "patient-1",
          professional_id: "prof-1",
          site_id: "site-1",
          availability_id: "slot-1",
        }),
      }),
    );
    expect(result).toEqual(appointment);
  });

  it("throws an ApiError with the backend's user_message on failure", async () => {
    const authorizedFetch = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(409, { user_message: "Slot no longer available" }));

    await expect(
      scheduleAppointment(authorizedFetch, {
        patientId: "patient-1",
        professionalId: "prof-1",
        siteId: "site-1",
        availabilityId: "slot-1",
      }),
    ).rejects.toMatchObject(new ApiError(409, "Slot no longer available"));
  });
});

describe("rescheduleAppointment", () => {
  it("posts the new availability id to the appointment's reschedule route", async () => {
    const authorizedFetch = vi.fn().mockResolvedValueOnce(jsonResponse(200, appointment));

    const result = await rescheduleAppointment(authorizedFetch, {
      appointmentId: "appt-1",
      newAvailabilityId: "slot-2",
    });

    expect(authorizedFetch).toHaveBeenCalledWith(
      "/appointments/appt-1/reschedule",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "Content-Type": "application/json" }),
        body: JSON.stringify({ new_availability_id: "slot-2" }),
      }),
    );
    expect(result).toEqual(appointment);
  });
});

describe("cancelAppointment", () => {
  it("posts to the appointment's cancel route with no body", async () => {
    const authorizedFetch = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, { ...appointment, status: "cancelled" }));

    const result = await cancelAppointment(authorizedFetch, "appt-1");

    expect(authorizedFetch).toHaveBeenCalledWith(
      "/appointments/appt-1/cancel",
      expect.objectContaining({ method: "POST" }),
    );
    expect(result.status).toBe("cancelled");
  });
});

describe("sendReminder", () => {
  it("posts to the appointment's reminder route and returns delivery status", async () => {
    const response: ReminderResponse = { delivered: true };
    const authorizedFetch = vi.fn().mockResolvedValueOnce(jsonResponse(200, response));

    const result = await sendReminder(authorizedFetch, "appt-1");

    expect(authorizedFetch).toHaveBeenCalledWith(
      "/appointments/appt-1/reminder",
      expect.objectContaining({ method: "POST" }),
    );
    expect(result).toEqual(response);
  });
});
