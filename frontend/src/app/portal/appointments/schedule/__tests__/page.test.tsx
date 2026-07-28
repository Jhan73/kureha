import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useRouter } from "next/navigation";
import SchedulePage from "../page";
import { useAuth } from "@/lib/auth/auth-context";
import type { AuthContextValue } from "@/lib/auth/auth-context";
import { scheduleAppointment } from "@/lib/api/scheduling";
import { ApiError } from "@/lib/api/client";
import type { AppointmentResponse } from "@/lib/api/types";

vi.mock("@/lib/auth/auth-context", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/auth/auth-context")>(
      "@/lib/auth/auth-context",
    );
  return { ...actual, useAuth: vi.fn() };
});
vi.mock("@/lib/api/scheduling", () => ({
  scheduleAppointment: vi.fn(),
}));
vi.mock("next/navigation", () => ({ useRouter: vi.fn() }));

const appointment: AppointmentResponse = {
  id: "appt-1",
  tenant_id: "tenant-1",
  site_id: "site-1",
  patient_id: "patient-1",
  professional_id: "prof-1",
  starts_at: "2026-08-01T10:00:00.000Z",
  ends_at: "2026-08-01T10:30:00.000Z",
  status: "scheduled",
};

function mockAuth(overrides: Partial<AuthContextValue>) {
  vi.mocked(useAuth).mockReturnValue({
    accessToken: "access-1",
    user: { userId: "user-1", role: "patient" },
    login: vi.fn(),
    logout: vi.fn(),
    silentRefresh: vi.fn().mockResolvedValue(false),
    authorizedFetch: vi.fn(),
    ...overrides,
  });
}

function fillForm({
  patientId,
  professionalId,
  siteId,
  availabilityId,
}: {
  patientId?: string;
  professionalId?: string;
  siteId?: string;
  availabilityId?: string;
}) {
  if (patientId !== undefined) {
    fireEvent.change(screen.getByLabelText(/patient id/i), { target: { value: patientId } });
  }
  if (professionalId !== undefined) {
    fireEvent.change(screen.getByLabelText(/professional id/i), {
      target: { value: professionalId },
    });
  }
  if (siteId !== undefined) {
    fireEvent.change(screen.getByLabelText(/site id/i), { target: { value: siteId } });
  }
  if (availabilityId !== undefined) {
    fireEvent.change(screen.getByLabelText(/availability id/i), {
      target: { value: availabilityId },
    });
  }
}

describe("SchedulePage", () => {
  beforeEach(() => {
    vi.mocked(useRouter).mockReturnValue({
      push: vi.fn(),
      replace: vi.fn(),
      back: vi.fn(),
      forward: vi.fn(),
      refresh: vi.fn(),
      prefetch: vi.fn(),
    });
  });

  it("redirects to /login through RequireAuth when unauthenticated", async () => {
    const replace = vi.fn();
    vi.mocked(useRouter).mockReturnValue({
      push: vi.fn(),
      replace,
      back: vi.fn(),
      forward: vi.fn(),
      refresh: vi.fn(),
      prefetch: vi.fn(),
    });
    mockAuth({ accessToken: null, silentRefresh: vi.fn().mockResolvedValue(false) });

    render(<SchedulePage />);

    expect(screen.queryByLabelText(/patient id/i)).toBeNull();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  });

  it("validates that all fields are required before submitting", () => {
    mockAuth({});
    render(<SchedulePage />);

    fireEvent.click(screen.getByRole("button", { name: /schedule appointment/i }));

    expect(screen.getByText(/all fields are required/i)).toBeInTheDocument();
    expect(scheduleAppointment).not.toHaveBeenCalled();
  });

  it("submits the form and shows the created appointment on success", async () => {
    const authorizedFetch = vi.fn();
    mockAuth({ authorizedFetch });
    vi.mocked(scheduleAppointment).mockResolvedValueOnce(appointment);

    render(<SchedulePage />);
    fillForm({
      patientId: "patient-1",
      professionalId: "prof-1",
      siteId: "site-1",
      availabilityId: "slot-1",
    });
    fireEvent.click(screen.getByRole("button", { name: /schedule appointment/i }));

    await waitFor(() =>
      expect(scheduleAppointment).toHaveBeenCalledWith(authorizedFetch, {
        patientId: "patient-1",
        professionalId: "prof-1",
        siteId: "site-1",
        availabilityId: "slot-1",
      }),
    );
    expect(await screen.findByText("appt-1")).toBeInTheDocument();
  });

  it("shows the backend's error message on failure", async () => {
    mockAuth({});
    vi.mocked(scheduleAppointment).mockRejectedValueOnce(
      new ApiError(409, "Slot no longer available"),
    );

    render(<SchedulePage />);
    fillForm({
      patientId: "patient-1",
      professionalId: "prof-1",
      siteId: "site-1",
      availabilityId: "slot-1",
    });
    fireEvent.click(screen.getByRole("button", { name: /schedule appointment/i }));

    expect(await screen.findByText("Slot no longer available")).toBeInTheDocument();
  });

  // Spec `patient-self-service-portal` -> "Consent Gate Enforced in Portal"
  // -> "Pending consent blocks form submission" (verify-report #414 gap
  // closure): the backend's new `consent_required`/403 envelope is not a
  // new error shape the frontend needs to special-case -- it flows through
  // the SAME generic `ApiError` message display every other backend error
  // already uses. This test pins that behavior specifically for the
  // consent scenario, not just "some ApiError".
  it("blocks submission and shows the consent message when the backend denies for missing consent", async () => {
    mockAuth({});
    vi.mocked(scheduleAppointment).mockRejectedValueOnce(
      new ApiError(403, "You must accept the informed consent before continuing."),
    );

    render(<SchedulePage />);
    fillForm({
      patientId: "patient-1",
      professionalId: "prof-1",
      siteId: "site-1",
      availabilityId: "slot-1",
    });
    fireEvent.click(screen.getByRole("button", { name: /schedule appointment/i }));

    expect(
      await screen.findByText("You must accept the informed consent before continuing."),
    ).toBeInTheDocument();
    expect(screen.queryByText("appt-1")).not.toBeInTheDocument();
  });
});
