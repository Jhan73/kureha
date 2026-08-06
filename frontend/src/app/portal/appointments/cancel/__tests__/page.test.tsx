import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useRouter } from "next/navigation";
import CancelPage from "../page";
import { useAuth } from "@/lib/auth/auth-context";
import type { AuthContextValue } from "@/lib/auth/auth-context";
import { cancelAppointment } from "@/lib/api/scheduling";
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
  cancelAppointment: vi.fn(),
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
  status: "cancelled",
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

describe("CancelPage", () => {
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

    render(<CancelPage />);

    expect(screen.queryByLabelText(/appointment id/i)).toBeNull();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  });

  it("validates that the appointment id is required before submitting", () => {
    mockAuth({});
    render(<CancelPage />);

    fireEvent.click(screen.getByRole("button", { name: /cancel appointment/i }));

    expect(screen.getByText(/appointment id is required/i)).toBeInTheDocument();
    expect(cancelAppointment).not.toHaveBeenCalled();
  });

  it("submits the form and shows the cancelled appointment on success", async () => {
    const authorizedFetch = vi.fn();
    mockAuth({ authorizedFetch });
    vi.mocked(cancelAppointment).mockResolvedValueOnce(appointment);

    render(<CancelPage />);
    fireEvent.change(screen.getByLabelText(/appointment id/i), {
      target: { value: "appt-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: /cancel appointment/i }));

    await waitFor(() => expect(cancelAppointment).toHaveBeenCalledWith(authorizedFetch, "appt-1"));
    expect(await screen.findByText("cancelled")).toBeInTheDocument();
  });

  it("shows the backend's error message on failure", async () => {
    mockAuth({});
    vi.mocked(cancelAppointment).mockRejectedValueOnce(
      new ApiError(404, "Appointment not found"),
    );

    render(<CancelPage />);
    fireEvent.change(screen.getByLabelText(/appointment id/i), {
      target: { value: "does-not-exist" },
    });
    fireEvent.click(screen.getByRole("button", { name: /cancel appointment/i }));

    expect(await screen.findByText("Appointment not found")).toBeInTheDocument();
  });

  it("blocks submission and shows the consent message when the backend denies for missing consent", async () => {
    mockAuth({});
    vi.mocked(cancelAppointment).mockRejectedValueOnce(
      new ApiError(403, "You must accept the informed consent before continuing."),
    );

    render(<CancelPage />);
    fireEvent.change(screen.getByLabelText(/appointment id/i), {
      target: { value: "appt-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: /cancel appointment/i }));

    expect(
      await screen.findByText("You must accept the informed consent before continuing."),
    ).toBeInTheDocument();
  });
});
