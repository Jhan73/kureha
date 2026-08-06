import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useRouter } from "next/navigation";
import ReschedulePage from "../page";
import { useAuth } from "@/lib/auth/auth-context";
import type { AuthContextValue } from "@/lib/auth/auth-context";
import { rescheduleAppointment } from "@/lib/api/scheduling";
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
  rescheduleAppointment: vi.fn(),
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
  status: "rescheduled",
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
  appointmentId,
  newAvailabilityId,
}: {
  appointmentId?: string;
  newAvailabilityId?: string;
}) {
  if (appointmentId !== undefined) {
    fireEvent.change(screen.getByLabelText(/appointment id/i), {
      target: { value: appointmentId },
    });
  }
  if (newAvailabilityId !== undefined) {
    fireEvent.change(screen.getByLabelText(/new availability id/i), {
      target: { value: newAvailabilityId },
    });
  }
}

describe("ReschedulePage", () => {
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

    render(<ReschedulePage />);

    expect(screen.queryByLabelText(/appointment id/i)).toBeNull();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  });

  it("validates that all fields are required before submitting", () => {
    mockAuth({});
    render(<ReschedulePage />);

    fireEvent.click(screen.getByRole("button", { name: /reschedule appointment/i }));

    expect(screen.getByText(/all fields are required/i)).toBeInTheDocument();
    expect(rescheduleAppointment).not.toHaveBeenCalled();
  });

  it("submits the form and shows the updated appointment on success", async () => {
    const authorizedFetch = vi.fn();
    mockAuth({ authorizedFetch });
    vi.mocked(rescheduleAppointment).mockResolvedValueOnce(appointment);

    render(<ReschedulePage />);
    fillForm({ appointmentId: "appt-1", newAvailabilityId: "slot-2" });
    fireEvent.click(screen.getByRole("button", { name: /reschedule appointment/i }));

    await waitFor(() =>
      expect(rescheduleAppointment).toHaveBeenCalledWith(authorizedFetch, {
        appointmentId: "appt-1",
        newAvailabilityId: "slot-2",
      }),
    );
    expect(await screen.findByText("rescheduled")).toBeInTheDocument();
  });

  it("shows the backend's error message on failure", async () => {
    mockAuth({});
    vi.mocked(rescheduleAppointment).mockRejectedValueOnce(
      new ApiError(409, "Target slot is unavailable"),
    );

    render(<ReschedulePage />);
    fillForm({ appointmentId: "appt-1", newAvailabilityId: "slot-2" });
    fireEvent.click(screen.getByRole("button", { name: /reschedule appointment/i }));

    expect(await screen.findByText("Target slot is unavailable")).toBeInTheDocument();
  });

  it("blocks submission and shows the consent message when the backend denies for missing consent", async () => {
    mockAuth({});
    vi.mocked(rescheduleAppointment).mockRejectedValueOnce(
      new ApiError(403, "You must accept the informed consent before continuing."),
    );

    render(<ReschedulePage />);
    fillForm({ appointmentId: "appt-1", newAvailabilityId: "slot-2" });
    fireEvent.click(screen.getByRole("button", { name: /reschedule appointment/i }));

    expect(
      await screen.findByText("You must accept the informed consent before continuing."),
    ).toBeInTheDocument();
  });
});
